from io import StringIO
import sys
import platform

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

from langchain_ollama import ChatOllama
from langchain_ollama import ChatOllama
from langchain_classic import hub # works
from langchain_core.tools import tool
from langchain_classic.agents import AgentExecutor, create_react_agent

# CODE_MODEL = 'qwen2.5-coder:32b-instruct-q3_K_M'  # works
# CODE_MODEL = 'qwen2.5-coder:7b' # works, not works sometimes
# CODE_MODEL = 'gpt-oss:20b'  # not works
# CODE_MODEL = 'gemma4:26b' # works
CODE_MODEL = 'mdq100/qwen3.5-coder:35b'  # works, not works sometimes

FONT_SIZE = 12
file_state = {'last_file_path': None}
context = []
# GUI log widget reference; set in gui_main().
gui_output_widget = None
IS_DEBUG = True

# LangChain expects messages in a specific format. We build a list of ChatMessage objects.
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
# Do not use this one, system_message0
# because the LLM will the steps whatever the user might input
system_messages = [
    SystemMessage(content=(
        "You are a software developer who is good at coding, debugging, and analyzeing using the provided tools. "
        "Solve problems by interleaving Thought, Action, and Observation. "
        "You do not have to follow sequence of the available tools if some tools are not needed. "
        "Just finish the job if no more actions have to be done. "
        "Do not repeat actions unless it is necessary. "
        "If the questions are not related to code or the Available Tools mentioned below, just answer the general question. "        
        "When using tool, read_file, the exact file path that is given must be used as the Input. "
        "Available Tools: \n"
        "- read_file: Read content of a file. Input: filename string only.\n"
        "- sandbox_exec: Execute Python code. Input: pure python code.\n\n"        
        "Format: \n"
        "Thought: [your reasoning]\n"
        "Action: [tool_name]: [input]\n"
        "Observation: [result from tool]\n"
        "... (repeat until solved)\n"
        "Answer: [your final conclusion]"
    ))
]


def print_msg(message):    
    global gui_output_widget
    if gui_output_widget is not None:
        try:
            gui_output_widget.after(0, lambda: append_output_text(gui_output_widget, message))
        except Exception:
            append_output_text(gui_output_widget, message)
    else:
        print(message)


def debug_log(message):
    if IS_DEBUG:
        print_msg(f"DEBUG: {message}")    


# --- TOOLS ---
@tool("sandbox_exec")
def sandbox_exec(code: str) -> str:
    """
    Cleans markdown and execute *code* in a fresh global namespace.
    Returns the printed output or an error string.
    """
    debug_log("sandbox_exec()")
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

@tool("python_repl")
def python_repl(code: str) -> str:
    """
    Cleans markdown and executes Python code.
    This function might modify the original code.
    """
    debug_log("python_repl()")
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

@tool("read_file")
def read_file(path_input: str) -> str:
    """Reads a file using absolute or relative paths."""
    debug_log(f"read_file().path_input = {path_input}")
    # Strip quotes/backticks the LLM might add
    path = path_input.strip().strip('`').strip("'").strip('"')    
    # Resolve path
    target_path = os.path.abspath(path) if not os.path.isabs(path) else path    
    return read_file_content(target_path)    

@tool
def noop(input: str) -> str:
    """Does nothing – useful when the agent needs to finish without calling a real tool."""
    return ""  

# Define LangChain Tools
python_tools = [read_file, sandbox_exec]


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
        print_msg(f"Error: file not found: {path}")
        return None
    except PermissionError:
        print_msg(f"Error: permission denied for file: {path}")
        return None
    except Exception as exc:
        print_msg(f"Error reading file {path}: {exc}")
        return None


def is_related_to_file(user_input, file_path):
    return file_path or is_display_request(user_input)

    
def reform_user_input(user_input):
    local_input = user_input
    temp_file_path = extract_file_path(local_input)
    debug_log(f"process_gui_request: file_path: {temp_file_path}")
    if not temp_file_path:
        temp_file_path = file_state.get('last_file_path')
        debug_log(f"reform_user_input: Using last file path: {temp_file_path}")            
    file_content = None                
    if temp_file_path:
        debug_log(f"reform_user_input: last file path before update: {file_state.get('last_file_path')}")
        debug_log(f"reform_user_input: Reading file: {temp_file_path}")
        file_state['last_file_path'] = temp_file_path
        file_content = read_file_content(temp_file_path)
        if file_content is None:                    
            print_msg(f"Could not read the requested file: {temp_file_path}")
        else:
            debug_log(f"process_gui_request: file_content is not None")                                                
        local_input = format_user_input_for_read(
            local_input,
            temp_file_path,
            file_content
        )            
    else:                    
        print_msg("No file path detected in your input. Please include one or open a file first.")
        
    return local_input


def format_user_input_for_read(user_input, file_path=None, file_content=None):
    if file_path and file_content:
        return (
            f"\n\nUser question:\n{user_input}"
            f"File path: \n{file_path}"
            # f"\n\nFile content:\n{file_content}"
        )
    else:
        return user_input


def create_file_content_frame(parent, path, content):
    std_arrow = "arrow" if platform.system() == "Windows" else "left_ptr"
    frame = tk.Frame(parent, bd=1, relief='solid', cursor=std_arrow)
    label_widget = tk.Label(frame, text=f'File content: {os.path.basename(path)}',
                            anchor='w', font=('TkDefaultFont', FONT_SIZE, 'bold'), cursor=std_arrow)
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


def cancel_request(cancel_event, status_label, cancel_button):
    cancel_event.set()
    status_label.config(text='Cancelled', fg='orange', font=('TkDefaultFont', FONT_SIZE, 'bold'))
    cancel_button.pack_forget()


def process_gui_request(user_input, request_parent, status_label,
                        cancel_button, cancel_event, history_canvas=None):
    debug_log(f"process_gui_request: user_input: {user_input}")
    if not user_input.strip():
        status_label.config(text='Please enter a request.')
        return

    request_frame = tk.Frame(request_parent, bd=1, relief='solid', padx=4, pady=4)
    request_frame.pack(fill='x', padx=8, pady=4, expand=False)

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    request_header = tk.Label(request_frame, text=f"Request ({timestamp}): {user_input}", anchor='w', font=('TkDefaultFont', FONT_SIZE, 'bold'))
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
                                    bg='#f0f0f0', font=('TkDefaultFont', FONT_SIZE))
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
    append_response_text(">>> Processing your request, please wait...")
    if history_canvas is not None:
        history_canvas.after(100, lambda: history_canvas.yview_moveto(1.0))
    status_label.config(text='Processing...', fg='red', font=('TkDefaultFont', FONT_SIZE, 'bold'))
    cancel_event.clear()
    cancel_button.pack(side='right')
    cancel_button.config(command=lambda: cancel_request(cancel_event, status_label, cancel_button))

    global gui_output_widget
    gui_output_widget = request_output_widget

    def worker():
        try:     
            #if is_related_to_file(local_input, file_path):
            local_input = reform_user_input(user_input)

            # No need to display the file content here because the LLM will read the file content
            # in agent_workflow and we do not want to show the file content twice in the GUI
            # if should_display and file_content is not None:
            # file_frame = create_file_content_frame(content_pane, file_path, file_content)
            # content_pane.add(file_frame, minsize=100, stretch="always") # Added as a resizable pane
            
            debug_log("process_gui_request: time.time()")
            start_time = time.time()
            debug_log("process_gui_request: agent_workflow()")
            response = agent_workflow(local_input, cancel_event)            
            end_time = time.time()    
            debug_log(f"process_gui_request.Time taken for response: {end_time - start_time:.2f} seconds")
        
            if not cancel_event.is_set():                
                print_msg(f'\nAgent response:\n{response}')                
        except Exception as exc:
            if not cancel_event.is_set():
                print_msg(f'\nError: {exc}')                
        finally:
            if not cancel_event.is_set():
                add_to_context(user_input, response)
                status_label.after(0, lambda: status_label.config(text='Ready', fg='green', font=('TkDefaultFont', FONT_SIZE, 'bold')))
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
    # Center the window on screen
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.geometry('1000x800')  # Optional: keep original size if needed

    label = tk.Label(root, text='Enter your request and click Submit:',
                     font=('TkDefaultFont', FONT_SIZE, 'bold'))

    input_widget = ScrolledText(root, wrap='word', width=110, height=8, font=('TkDefaultFont', FONT_SIZE))

    button_frame = tk.Frame(root)

    shortcuts_label = tk.Label(root, text='Shortcuts: Ctrl+Enter = Submit, Ctrl+L = Clear, Ctrl+Q = Exit', anchor='w', fg='gray30', font=('TkDefaultFont', FONT_SIZE))

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

    output_label = tk.Label(history_frame, text='Output:', font=('TkDefaultFont', FONT_SIZE, 'bold'))
    output_label.pack(anchor='w')

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
            process_gui_request(text, history_frame, status_label, cancel_button, cancel_event, history_canvas)
            input_widget.delete('1.0', 'end')

    def on_clear(event=None):
        clear_output()

    default_status_font = ('TkDefaultFont', FONT_SIZE, 'bold')
    status_frame = tk.Frame(root)
    status_frame.pack(fill='x', padx=8, pady=(0, 8))

    # Frame to hold status text and cancel button together
    processing_frame = tk.Frame(status_frame)
    processing_frame.pack(side='left')

    status_label = tk.Label(processing_frame, text='Ready', fg='green', font=default_status_font)
    status_label.pack(side='left')

    cancel_button = tk.Button(processing_frame, text='Cancel', command=lambda: None,
                              font=('TkDefaultFont', FONT_SIZE))
    cancel_button.pack(side='left', padx=(8, 0))
    cancel_button.pack_forget()  # Hide initially

    cancel_event = threading.Event()

    global gui_output_widget
    gui_output_widget = None

    submit_button = tk.Button(button_frame, text='Submit', command=on_submit,
                              font=('TkDefaultFont', FONT_SIZE))
    submit_button.pack(side='left')

    browse_button = tk.Button(button_frame, text='Browse File', command=browse_file,
                              font=('TkDefaultFont', FONT_SIZE))
    browse_button.pack(side='left', padx=(8, 0))

    clear_button = tk.Button(button_frame, text='Clear Output', command=clear_output,
                             font=('TkDefaultFont', FONT_SIZE))
    clear_button.pack(side='left', padx=(8, 0))

    root.bind('<Control-Return>', on_submit)
    root.bind('<Control-l>', on_clear)
    root.bind('<Control-L>', on_clear)
    root.bind('<Control-q>', lambda event: root.destroy())

    exit_button = tk.Button(button_frame, text='Exit', command=root.destroy,
                            font=('TkDefaultFont', FONT_SIZE))    
    exit_button.pack(side='left', padx=(8, 0))

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
                print_msg("More? (or Enter to submit, or type 'exit' to quit)")
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


def add_to_context(user_input, response, max_history=10):
    """Appends the latest interaction to the history list."""
    context.append({
        'user_input': user_input,
        'response': response,
    })
    if len(context) > max_history:
        # context.pop(0)  # Remove the oldest entry to maintain the max history size  
        del context[0]  # Alternative way to remove the oldest entry


# --- AGENT ENGINE ---
def agent_workflow(user_input, cancel_event=None):
    """
    Uses LangChain to orchestrate the ReAct agent with Ollama.
    """
    debug_log("agent_workflow: Started agent_workflow")
    if not user_input.strip():
        debug_log("agent_workflow: No user input provided.")

    debug_log("agent_workflow: Setting messages with system prompt and history")    
    # 1. Prepare the History (Context)
    # Add history
    messages = system_messages
    for entry in context:
        messages.append(HumanMessage(content=entry.get('user_input', '')))
        messages.append(AIMessage(content=entry.get('response', '')))

    # Add current user input
    messages.append(HumanMessage(content=user_input))

    # 2. Initialize LangChain Components
    debug_log("agent_workflow: ChatOllama()")
    llm = ChatOllama(
        model=CODE_MODEL,
        temperature=0.0,
        num_ctx=8192,
        timeout=None,
        streaming=False,
        stop=None
    )
    # debug_log(f"{llm.invoke('Hello, who are you?')}")

    full_agent_log = ""

    try:
        # 3. Create the Prompt
        # We use the ReAct prompt template from the hub
        debug_log("DEBUG.agent_workflow: hub.pull()")
        prompt = hub.pull("hwchase17/react")            
    except Exception as e:
        error_msg = f"agent_workflow.hub.pull().Exception: {str(e)}"
        debug_log(f"DEBUG.agent_workflow.hub.pull.Exception: {error_msg}")
        full_agent_log += f"\n{error_msg}\n"
        return full_agent_log    
        
    try:    
        # 4. Create the Agent
        debug_log("DEBUG.agent_workflow: create_react_agent()")
        agent = create_react_agent(llm, python_tools, prompt)        
    except Exception as e:
        error_msg = f"agent_workflow.create_react_agent().Exception error: {str(e)}"
        debug_log(f"DEBUG.agent_workflow.create_react_agent.Exception")
        full_agent_log += f"\n{error_msg}\n"
        return full_agent_log
  
    try:
        # 5. Execute the Agent
        agent_executor = AgentExecutor(
            agent=agent,
            tools=python_tools,
            verbose=True,
            handle_parsing_errors=True,
            # max_iterations=10
        )        
        debug_log("DEBUG.agent_workflow: agent_executor.invoke()")
        # result = agent_executor.invoke(input = {"input": user_input})
        full_prompt = "\n".join(msg.content for msg in messages)
        result = agent_executor.invoke(input = {"input": full_prompt})
        # result = agent_executor.invoke(input = {"input": user_input, "chat_history": messages})
        full_agent_log = result.get("output")
    except Exception as e:
        error_msg = f"agent_workflow.agent_executor.invoke().Exception: {str(e)}"
        debug_log(f"DEBUG.agent_workflow.run agent_executor.invoke().Exception")
        full_agent_log += f"\n{error_msg}\n"
        return full_agent_log

    return full_agent_log


def main():
    justEntered = True
    while True:
        if justEntered:
            print_msg("\nHow can I help you? (or Enter to quit):")        
            justEntered = False
        else:
            print_msg("\nWhat else can I assist you with? (or Enter to quit):")
        if PromptSession is not None:
            print_msg("(Use Ctrl+O for a newline, Enter to submit.)")
        user_input = get_multiline_input('-> ')
        
        if user_input == EXIT_COMMAND:
            print_msg("Goodbye!")
            return
        
        debug_log(f"user_input: {user_input}")
        if not user_input.strip():
            print_msg("Goodbye!")
            return

        # file_path = extract_file_path(user_input)
        # debug_log(f"main.file_path: {file_path}")  
        print_msg("\nProcessing your request, please wait...")        
        start_time = time.time()       
        response = agent_workflow(user_input)
        end_time = time.time()    
        print_msg(f"\nTime taken for response: {end_time - start_time:.2f} seconds")

        if response is not None:
            print_msg(f"\nAgent response:\n {response}")
        else:
            print_msg("Failed to get a response from the Agent.")        
    
        add_to_context(user_input, response)
            
if __name__ == "__main__":
    try:
        gui_main()
    except Exception as e:
        print_msg(f"GUI unavailable, falling back to CLI: {e}")
        main()
