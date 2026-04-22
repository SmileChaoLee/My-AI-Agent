from io import StringIO
import sys
import platform

import ollama
import os
import re
import time
import threading

try:
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText
    from tkinter import filedialog
except ImportError as exc:
    tk = None
    ScrolledText = None
    filedialog = None    
else:    
    print("Successfully imported tkinter for GUI mode.")

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:
    PromptSession = None
    KeyBindings = None

# CODE_MODEL = 'qwen2.5-coder:32b-instruct-q3_K_M'  # not works well on calling tools, some times works
# CODE_MODEL = 'qwen2.5-coder:7b' # not works on calling tools
CODE_MODEL = 'gpt-oss:20b'  # works on calling tools
# CODE_MODEL = 'gemma4:26b' # works on calling tools
# CODE_MODEL = 'mdq100/qwen3.5-coder:35b'  # not works in this codebase

# --- TOOLS ---
def sandbox_exec(code: str) -> str:
    """
    Cleans markdown and execute *code* in a fresh global namespace.
    Returns the printed output or an error string.
    """
    debug_log(f"DEBUG.sandbox_exec()")
    clean = re.sub(r'^```python\n|^```\n|```$', '', code.strip(), flags=re.MULTILINE)
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    local_vars = {} 
    try:
        exec(clean, local_vars)
        return sys.stdout.getvalue() or "Executed successfully (no output)."
    except Exception as e:
        return f"Error: {e}"
    finally:
        sys.stdout = old_stdout

def python_repl(code: str) -> str:
    """
    Cleans markdown and executes Python code.
    This function might modify the original code.
    """
    debug_log(f"DEBUG.python_repl()")
    # Remove markdown backticks and language tags
    clean_code = re.sub(r'^```python\n|^```\n|```$', '', code.strip(), flags=re.MULTILINE)    
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    try:
        # Execute in globals to maintain state across turns
        exec(clean_code, globals())
        return redirected_output.getvalue() or "Executed successfully (no output)."
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        sys.stdout = old_stdout    

def read_file(path_input: str) -> str:
    """Reads a file using absolute or relative paths."""
    debug_log(f"DEBUG.read_file: path_input = {path_input}")
    # Strip quotes/backticks the LLM might add
    path = path_input.strip().strip('`').strip("'").strip('"')    
    # Resolve path
    target_path = os.path.abspath(path) if not os.path.isabs(path) else path    
    return read_file_content(target_path)    

AVAILABLE_TOOLS = {"python_repl": python_repl, "sandbox_exec": sandbox_exec, "read_file": read_file}

# GUI log widget reference; set in gui_main().
gui_output_widget = None

def prompt_tkinter_install_help():
    if tk is not None:
        return

    print('\nTkinter is not available in this Python environment.')
    print('The GUI requires tkinter to run. You can continue using the CLI mode.')
    choice = input('Would you like installation instructions for tkinter? (y/n): ').strip().lower()
    if choice.startswith('y'):
        print('\nInstallation instructions for tkinter:')
        print('- Ubuntu / Debian: sudo apt-get install python3-tk')
        print('- Fedora / RHEL: sudo dnf install python3-tkinter')
        print('- Arch Linux: sudo pacman -S tk')
        print('- macOS: install Python from python.org with Tcl/Tk support, or use Homebrew with `brew install python-tk`')
        print('- Windows: install the official Python from python.org and include Tcl/Tk support during setup')
        print('\nAfter installation, rerun this program.')
    print('Continuing in CLI mode.\n')


def is_file_request_from_userinput(text: str) -> bool:
    """
    Return True if *text* contains a keyword that indicates the user is
    asking to read or otherwise access a file.
    """
    if not isinstance(text, str):
        return False
    return is_file_request(text)


FILE_REQUEST_PATTERNS = [
    r'\bread( the)? file\b',
    r'\bopen( the)? file\b',
    r'\bload( the)? file\b',
    r'\banalyze( the)? file\b',
    r'\bread from (the )?file\b',
    r'\bshow( me)?( the)? file\b',
    r'\bsend.*file\b',
    r'\battach file\b',
    r'\bfile content\b'
    r'\bfile contents\b'
]


FILE_PATH_PATTERN = r'[A-Za-z0-9_\-./\\]+\.[A-Za-z0-9]+'

def is_file_request(text):
    text = text.lower()
    return any(re.search(pattern, text) for pattern in FILE_REQUEST_PATTERNS)


def extract_file_path(text):
    # Try quoted file paths first
    quoted = re.search(r'"([^"]+)"|\'([^\']+)\'', text)
    if quoted:
        return quoted.group(1) or quoted.group(2)

    candidate_paths = re.findall(FILE_PATH_PATTERN, text)
    if candidate_paths:
        return candidate_paths[0]
    return None


DISPLAY_FILE_PATTERNS = [
    r'\b(show|display|print)( me)?( the)?( .+)?\b',
]


def is_display_request(text):
    if not isinstance(text, str):
        return False
    text = text.lower()
    return any(re.search(pattern, text) for pattern in DISPLAY_FILE_PATTERNS)


def read_file_content(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: file not found: {path}")
        return None
    except PermissionError:
        print(f"Error: permission denied for file: {path}")
        return None
    except Exception as exc:
        print(f"Error reading file {path}: {exc}")
        return None


def format_user_input_for_read(user_input, file_path=None, file_content=None):
    if file_path and file_content:
        return (
            f"File path: \n{file_path}"
            f"\n\nFile content:\n{file_content}"
            f"\n\nUser question:\n{user_input}"
        )
    else:
        return user_input


def create_file_content_frame(parent, path, content):
    std_arrow = "arrow" if platform.system() == "Windows" else "left_ptr"
    frame = tk.Frame(parent, bd=1, relief='solid', cursor=std_arrow)
    label_widget = tk.Label(frame, text=f'File content: {os.path.basename(path)}',
                            anchor='w', font=('TkDefaultFont', 10, 'bold'), cursor=std_arrow)
    label_widget.pack(fill='x', padx=4, pady=(4, 0))
    toolbar = tk.Frame(frame)
    toolbar.pack(fill='x', padx=4, pady=4)

    def copy_file_view_content():
        try:
            frame.clipboard_clear()
            frame.clipboard_append(content)
            frame.update()
        except Exception:
            pass

    copy_button = tk.Button(toolbar, text='📋 Copy', command=copy_file_view_content)
    copy_button.pack(side='left')

    text_widget = ScrolledText(frame, wrap='word', width=110, height=12, state='disabled')
    text_widget.pack(fill='both', expand=True, padx=4, pady=(0, 4))
    text_widget.configure(state='normal')
    text_widget.insert('1.0', content)
    text_widget.configure(state='disabled')

    #frame.pack(fill='both', padx=8, pady=(0, 8), expand=False)
    return frame


def append_output_text(widget, text):
    widget.configure(state='normal')
    widget.insert('end', text + '\n')
    widget.see('end')
    widget.configure(state='disabled')


def debug_log(message):
    global gui_output_widget
    if gui_output_widget is not None:
        try:
            gui_output_widget.after(0, lambda: append_output_text(gui_output_widget, message))
        except Exception:
            append_output_text(gui_output_widget, message)
    else:
        print(message)


def cancel_request(cancel_event, status_label, cancel_button):
    cancel_event.set()
    status_label.config(text='Cancelled', fg='orange', font=('TkDefaultFont', 10, 'bold'))
    cancel_button.pack_forget()


def process_gui_request(user_input, context, request_parent, status_label,
                        cancel_button, cancel_event, file_state, history_canvas=None):
    debug_log(f"DEBUG.process_gui_request: user_input: {user_input}")
    if not user_input.strip():
        status_label.config(text='Please enter a request.')
        return

    request_frame = tk.Frame(request_parent, bd=1, relief='solid', padx=4, pady=4)
    request_frame.pack(fill='x', padx=8, pady=4, expand=False)

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    request_header = tk.Label(request_frame, text=f"Request ({timestamp}): {user_input}", anchor='w', font=('TkDefaultFont', 10, 'bold'))
    request_header.pack(fill='x')

    # The following is used anymore
    """
    content_pane = tk.PanedWindow(
        request_frame, 
        orient=tk.VERTICAL, 
        sashrelief='raised',
        sashwidth=6,
        showhandle=True,
        cursor="sb_v_double_arrow",     # Standard pointer on hover
        sashcursor="sb_v_double_arrow"  # Standard pointer during drag
    )
    content_pane.pack(fill='both', expand=True, pady=4)
    """

    request_output_widget = tk.Text(request_frame, wrap='word', state='disabled', 
                                    borderwidth=0, highlightthickness=0, 
                                    bg='#f0f0f0', font=('TkDefaultFont', 10))
    request_output_widget.pack(
        fill='both',  # Essential: fills the space
        expand=True,  # Essential: grows with the window
        side='bottom' # Or wherever you place it
    )

    def append_response_text(text):
        request_output_widget.configure(state='normal')
        request_output_widget.insert('end', text + '\n')
        request_output_widget.see('end')
        request_output_widget.configure(state='disabled')
        if history_canvas is not None:
            history_canvas.after(50, lambda: history_canvas.yview_moveto(1.0))

    append_response_text(f">>> {user_input}")
    if history_canvas is not None:
        history_canvas.after(100, lambda: history_canvas.yview_moveto(1.0))
    status_label.config(text='Processing...', fg='red', font=('TkDefaultFont', 10, 'bold'))
    cancel_event.clear()
    cancel_button.pack(side='right')
    cancel_button.config(command=lambda: cancel_request(cancel_event, status_label, cancel_button))

    global gui_output_widget
    gui_output_widget = request_output_widget

    def worker():
        try:        
            local_input = user_input          
            file_path = extract_file_path(local_input)
            debug_log(f"DEBUG.process_gui_request: file_path: {file_path}")
            if not file_path:
                file_path = file_state.get('last_file_path')
                if file_path and is_display_request(local_input):
                    debug_log(f"DEBUG.process_gui_request: Using last file path: {file_path}")

            should_display = False
            file_content = None
            if file_path:
                debug_log(f"DEBUG.process_gui_request: last file path before update: {file_state.get('last_file_path')}")
                debug_log(f"DEBUG.process_gui_request: Reading file: {file_path}")
                file_state['last_file_path'] = file_path
                file_content = read_file_content(file_path)
                if file_content is None:
                    request_output_widget.after(0, lambda: append_response_text(f'Could not read the requested file: {file_path}'))
                    return
                debug_log(f"DEBUG.process_gui_request: file_content is not None")                
                should_display = is_display_request(local_input)               
                #local_input = format_user_input_for_read(
                #    user_input,
                #    file_path,
                #    file_content
                #)
                local_input = user_input
            elif is_display_request(local_input):
                request_output_widget.after(0, lambda: append_response_text('No file path detected in your input. Please include one or open a file first.'))
                return

            # No need to display the file content here because the LLM will read the file content
            # in agent_workflow and we do not want to show the file content twice in the GUI
            # if should_display and file_content is not None:
                # file_frame = create_file_content_frame(content_pane, file_path, file_content)
                # content_pane.add(file_frame, minsize=100, stretch="always") # Added as a resizable pane         

            start_time = time.time()
            response = agent_workflow(local_input, context, cancel_event)
            end_time = time.time()    
            debug_log(f"DEBUG.process_gui_request.Time taken for response: {end_time - start_time:.2f} seconds")
        
            if not cancel_event.is_set():              
                add_to_context(context, user_input, response)            
                request_output_widget.after(0, lambda: append_response_text(f'Agent response:\n{response}'))
        except Exception as exc:
            if not cancel_event.is_set():
                request_output_widget.after(0, lambda: append_response_text(f'Error: {exc}'))
        finally:
            if not cancel_event.is_set():
                status_label.after(0, lambda: status_label.config(text='Ready', fg='green', font=('TkDefaultFont', 10, 'bold')))
            cancel_button.after(0, lambda: cancel_button.pack_forget())

    threading.Thread(target=worker, daemon=True).start()


def gui_main():
    if tk is None or ScrolledText is None:
        print('tkinter is not available; falling back to CLI.')
        prompt_tkinter_install_help()
        main()
        return

    try:
        root = tk.Tk()
    except Exception as exc:
        print(f'GUI startup failed ({exc}); falling back to CLI.')
        main()
        return

    root.title('Smile Coder GUI')
    root.geometry('1000x800')

    label = tk.Label(root, text='Enter your request and click Submit:')

    input_widget = ScrolledText(root, wrap='word', width=110, height=8)

    button_frame = tk.Frame(root)

    shortcuts_label = tk.Label(root, text='Shortcuts: Ctrl+Enter = Submit, Ctrl+L = Clear, Ctrl+Q = Exit', anchor='w', fg='gray30', font=('TkDefaultFont', 9))

    history_frame_container = tk.Frame(root)
    history_frame_container.pack(fill='both', padx=8, pady=(0, 8), expand=True)

    label.pack(anchor='w', padx=8, pady=(8, 0))

    input_widget.pack(fill='both', padx=8, pady=4, expand=False)

    shortcuts_label.pack(fill='x', padx=8, pady=(0, 4))

    button_frame.pack(fill='x', padx=8, pady=4)

    history_canvas = tk.Canvas(history_frame_container, bd=0, highlightthickness=0)
    history_canvas.pack(side='left', fill='both', expand=True)

    scrollbar = tk.Scrollbar(history_frame_container, orient='vertical', command=history_canvas.yview)
    scrollbar.pack(side='right', fill='y')

    history_canvas.configure(yscrollcommand=scrollbar.set)

    history_frame = tk.Frame(history_canvas)
    history_window = history_canvas.create_window((0, 0), window=history_frame, anchor='nw')

    def on_history_configure(event):
        history_canvas.configure(scrollregion=history_canvas.bbox('all'))
    history_frame.bind('<Configure>', on_history_configure)

    def on_canvas_configure(event):
        history_canvas.itemconfigure(history_window, width=event.width)
    history_canvas.bind('<Configure>', on_canvas_configure)

    output_label = tk.Label(history_frame, text='Output:')
    output_label.pack(anchor='w')

    file_state = {'last_file_path': None}

    def clear_output():
        for child in history_frame.winfo_children():
            child.destroy()
        output_label = tk.Label(history_frame, text='Output:')
        output_label.pack(anchor='w')

    def browse_file():
        if filedialog is None:
            return
        path = filedialog.askopenfilename(initialdir=os.getcwd(), title='Select a file')
        if path:
            if input_widget.get('1.0', 'end').strip():
                input_widget.insert('end', ' ' + path)
            else:
                input_widget.insert('end', path)

    def on_submit(event=None):
        text = input_widget.get('1.0', 'end').strip()
        if text:
            process_gui_request(text, gui_main.context, history_frame, status_label, cancel_button, cancel_event, file_state, history_canvas)
            input_widget.delete('1.0', 'end')

    def on_clear(event=None):
        clear_output()

    default_status_font = ('TkDefaultFont', 10, 'bold')
    status_frame = tk.Frame(root)
    status_frame.pack(fill='x', padx=8, pady=(0, 8))

    # Frame to hold status text and cancel button together
    processing_frame = tk.Frame(status_frame)
    processing_frame.pack(side='left')

    status_label = tk.Label(processing_frame, text='Ready', fg='green', font=default_status_font)
    status_label.pack(side='left')

    cancel_button = tk.Button(processing_frame, text='Cancel', command=lambda: None, font=('TkDefaultFont', 10, 'bold'))
    cancel_button.pack(side='left', padx=(8, 0))
    cancel_button.pack_forget()  # Hide initially

    cancel_event = threading.Event()

    global gui_output_widget
    gui_output_widget = None

    submit_button = tk.Button(button_frame, text='Submit', command=on_submit)
    submit_button.pack(side='left')

    browse_button = tk.Button(button_frame, text='Browse File', command=browse_file)
    browse_button.pack(side='left', padx=(8, 0))

    clear_button = tk.Button(button_frame, text='Clear Output', command=clear_output)
    clear_button.pack(side='left', padx=(8, 0))

    root.bind('<Control-Return>', on_submit)
    root.bind('<Control-l>', on_clear)
    root.bind('<Control-L>', on_clear)
    root.bind('<Control-q>', lambda event: root.destroy())

    exit_button = tk.Button(button_frame, text='Exit', command=root.destroy)
    exit_button.pack(side='left', padx=(8, 0))

    gui_main.context = []
    root.mainloop()


EXIT_COMMAND = "__EXIT_COMMAND__"

def get_multiline_input(prompt_text='-> '):
    """Read multiline user input with Ctrl+O for new lines and Enter to submit."""
    if PromptSession is None or KeyBindings is None:
        lines = []
        while True:
            if not lines:
                line = input(prompt_text)
            else:
                print("More? (or Enter to submit, or type 'exit' to quit)")
                line = input('-> ')

            if line.lower() == "exit":
                return EXIT_COMMAND
            if not line:
                break
            lines.append(line)
        return "\n".join(lines)

    kb = KeyBindings()

    @kb.add('c-o')
    def _(event):
        event.current_buffer.insert_text('\n')

    @kb.add('enter')
    def _(event):
        buffer = event.current_buffer
        event.app.exit(result=buffer.text)

    session = PromptSession(multiline=True, key_bindings=kb)
    try:
        return session.prompt(prompt_text)
    except (EOFError, KeyboardInterrupt):
        return ''


def add_to_context(context_list, user_input, response, max_history=10):
    """Appends the latest interaction to the history list."""
    context_list.append({
        'user_input': user_input,
        'response': response,
    })
    if len(context_list) > max_history:
        # context_list.pop(0)  # Remove the oldest entry to maintain the max history size  
        del context_list[0]  # Alternative way to remove the oldest entry


# --- AGENT ENGINE ---
def agent_workflow(user_input, context=[], cancel_event=None):
    if not user_input.strip():
        debug_log(f"DEBUG.agent_workflow: No user input provided.")
    
    # 1. Build the messages list
    # Setup the ReAct system prompt
    messages = [
        {'role': 'system', 'content': (
            "You are a coding and debugging expert using the provided tools."
            "Solve problems by interleaving Thought, Action, and Observation. "
            "Available Tools: \n"
            "- read_file: Read content of a file. Input: filename string only.\n"
            "- sandbox_exec: Execute Python code. Input: pure python code.\n\n"
            "Format: \n"
            "Thought: [your reasoning]\n"
            "Action: [tool_name]: [input]\n"
            "Observation: [result from tool]\n"
            "... (repeat until solved)\n"
            "Answer: [your final conclusion]"
        )},
    ]

    # 2. Add context to the conversation (if you want the model to see history)
    for entry in context:
        messages.append({'role': 'user', 'content': entry.get('user_input', '')})
        messages.append({'role': 'assistant', 'content': entry.get('response', '')})

    # 3. Add the current user input
    messages.append({'role': 'user', 'content': user_input})
    
    full_agent_log = ""    
    # 4. ReAct Loop (Limit to 5 turns to prevent infinite loops)
    for turn in range(5):
        debug_log(f"DEBUG.agent_workflow: turn = {turn}")
        if cancel_event and cancel_event.is_set():
            break
        
        tool_calls = []  # To store tool calls from the model
        message_content = ''
        try:
            # Use ollama.chat instead of generate            
            response = ollama.chat(
                model=CODE_MODEL,
                messages=messages,
                options={
                    'temperature': 0.0,                    
                    'num_ctx': 8192,
                    'stop': ["Observation:", "Observation"] # Force the model to stop here
                },
                tools=[read_file, sandbox_exec], # native tool support in .chat() with function calling                
            )
            if cancel_event and cancel_event.is_set():
                full_agent_log += '\n[CANCELLED]'
                break   # exit the streaming loop
            # In .chat(), the text is inside chunk['message']['content']
            # Handle text content (Reasoning)
            if 'message' in response and 'content' in response['message']:                
                message_content = response['message']['content']
                has_letters = bool(re.search(r'[a-zA-Z]', message_content))
                debug_log(f"DEBUG.agent_workflow.has_letters = {has_letters}.")            
                has_digits = bool(re.search(r'\d', message_content))
                debug_log(f"DEBUG.agent_workflow.has_digits  = {has_digits}.")                
                if has_letters or has_digits:
                    debug_log(f"DEBUG.agent_workflow.message_content has content.")
                    full_agent_log += f"\n{message_content}\n"                    
                    messages.append({'role': 'assistant', 'content': message_content})                                        
            # Handle tool calls (they arrive in the 'tool_calls' field)
            if 'message' in response and 'tool_calls' in response['message']:
                # We store these to process after the stream finishes
                tool_calls = response['message']['tool_calls']
                debug_log(f"DEBUG.agent_workflow.has tool_calls.")

            # The following login is for the native call in .chat() with tools
            # Check if the model wants to call tools
            if tool_calls:
                # Note: We include the tool_calls in the message so Ollama knows it asked for them
                messages.append({
                    'role': 'assistant', 
                    'content': message_content, 
                    'tool_calls': tool_calls
                })
                # Handle the tool calls
                for call in tool_calls:
                    tool_name = call.function.name
                    debug_log(f"DEBUG.agent_workflow.for call: tool_name = {tool_name}")
                    tool_args = call.function.arguments # This is a dictionary                
                    if tool_name in AVAILABLE_TOOLS:
                        # Execute the tool
                        observation = AVAILABLE_TOOLS[tool_name](**tool_args)
                        # Append the observation to the conversation
                        messages.append({
                            'role': 'tool',
                            'content': str(observation),
                            'name': tool_name
                        })
                        full_agent_log += f"\n[Tool Observation ({tool_name})] = \n{observation}\n"
            else:
                # messages.append({'role': 'assistant', 'content': message_content})
                # The following logic is for backward compatibility                
                # and instead outputs Action: ... in text
                # Check if we are done
                if "Answer:" in message_content:
                    debug_log(f"DEBUG.agent_workflow: Answer found in response.")
                    break   # exit the loop ( for _ in range(5) )            
                # Tool Execution Logic
                action_match = re.search(r"Action: (\w+): (.*)", message_content, re.DOTALL)
                debug_log(f"DEBUG.agent_workflow: action_match: {action_match}")
                if action_match:
                    tool_name, tool_input = action_match.groups()
                    debug_log(f"DEBUG.agent_workflow.action_match: tool_name = {tool_name}, tool_input = {tool_input}")
                    # Use your existing TOOLS dictionary
                    # observation = AVAILABLE_TOOLS.get(tool_name, lambda x: "Tool not found")(tool_input)
                    if tool_name in AVAILABLE_TOOLS:
                        observation = AVAILABLE_TOOLS.get(tool_name)(tool_input)                                                
                        obs_text = f"Observation: {observation}"
                        full_agent_log += f"\n{obs_text}\n"
                        messages.append({'role': 'user', 'content': obs_text})                
                else:
                    # If the model didn't provide an Action or Answer, stop or prompt it
                    break   # exit the loop ( for _ in range(5) )        
                    # continue

        except Exception as e:                        
            error_msg = f"Error: {e}"
            debug_log(f"DEBUG.agent_workflow.Exception: {error_msg}")
            full_agent_log += f"\n{error_msg}\n"
        
    return full_agent_log


def main():
    context = []
    m_file_path = None
    justEntered = True
    while True:
        if justEntered:
            print("\nHow can I help you? (or Enter to quit):")        
            justEntered = False
        else:
            print("\nWhat else can I assist you with? (or Enter to quit):")

        if PromptSession is not None:
            print("(Use Ctrl+O for a newline, Enter to submit.)")

        user_input = get_multiline_input('-> ')
        if user_input == EXIT_COMMAND:
            print("Goodbye!")
            return

        print(f"DEBUG: user_input: {user_input}")

        if not user_input.strip():
            print("Goodbye!")
            break

        file_path = extract_file_path(user_input)
        if file_path:
            m_file_path = file_path

            print(f"\nDEBUG: m_file_path: {m_file_path}")
            print(f"DEBUG: Reading file: {file_path}")
            
            file_content = read_file_content(file_path)
            if file_content is not None:
                # do not show the file content here because the LLM will read the file content
                # in agent_workflow and we do not want to show the file content twice in the CLI
                #if is_display_request(user_input):
                #    print(f"\nContent of {file_path}:")                                
                #    print(f"File content: \n{file_content}")
                #user_input = format_user_input_for_read(
                #    user_input,
                #    file_path,
                #    file_content
                #)
                print("file_content is not None.")
            else:
                print("Could not read the requested file. Try again.")
                continue
        
        print("\nProcessing your request, please wait...")        
        start_time = time.time()       
        
        response = agent_workflow(user_input, context)
        
        end_time = time.time()    
        print(f"\nTime taken for response: {end_time - start_time:.2f} seconds")

        if response is not None:
            print(f"\nAgent response:\n {response}")
        else:
            print("Failed to get a response from the Agent.")        
    
        add_to_context(context, user_input, response)
            
if __name__ == "__main__":
    try:
        gui_main()
    except Exception as e:
        print(f"GUI unavailable, falling back to CLI: {e}")
        main()
