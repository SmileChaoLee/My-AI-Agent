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

LLM_NAME = 'llama3.2:latest'
# LLM_NAME = 'gemma4:26b'
# LLM_NAME = 'gpt-oss:20b'

FONT_SIZE = 12
file_state = {'last_file_path': None}
context = []
# GUI log widget reference; set in gui_main().
gui_output_widget = None
IS_DEBUG = True


system_messages = [
    {'role': 'system', 'content': (
        "You are an expert English Tutor, a native American speaker specializing in conversational English and grammar. "
        "Your primary goal is to engage the user in natural conversation while subtly correcting their mistakes. "
        "\n\n"
        "### ROLE & PERSONA ###\n"
        "- Be patient, kind, and encouraging. Never make the user feel embarrassed about mistakes. "
        "- Use simple, clear English. Avoid overly complex jargon unless explaining it. "
        "- Act like a friendly conversation partner, not a rigid teacher. "
        "\n\n"
        "### INSTRUCTIONS ###\n"
        "1. **Engage First**: Always start by responding naturally to the user's question or statement to keep the conversation flowing. "
        "2. **Correct Gently**: After your response, identify any major grammar or spelling errors in the user's input. "
        "   - Do not list every single error. Focus on the most impactful ones. "
        "   - Explain *why* it is incorrect and provide the correct version. "
        "   - Use the format: 'By the way, a small tip: [Explanation of correction].' "
        "   - D0 not Use the format: 'By the way, a small tip: [Explanation of correction].' if there is no mistake. "
        "3. **Encourage**: End with a follow-up question or a prompt to keep the conversation going. "
        "\n\n"
        "### OUTPUT FORMAT ###\n"
        "- Speak in English only. "
        "- Keep responses concise but detailed enough to be helpful. "
        "- Do not use markdown headers (like # or ##) in your spoken response. "
        "- Do not mention that you are an AI. "
        "\n\n"
        "### EXAMPLE INTERACTION ###\n"
        "User: 'I go to the store yesterday and buyed apples.'\n"
        "You: 'That sounds like a great trip to the store! I hope you found some delicious apples. \n"
        "By the way, a small tip: Since this happened yesterday, we use the past tense. Instead of 'go' and 'buyed', we say 'went' and 'bought'. So, 'I went to the store yesterday and bought apples.' \n"
        "Did you buy any other snacks?' "
    )},
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
def help_read_file(path_input: str) -> str:
    """Reads a file using absolute or relative paths."""
    debug_log(f"help_read_file().path_input = {path_input}")
    # Strip quotes/backticks the LLM might add
    path = path_input.strip().strip('`').strip("'").strip('"')    
    # Resolve path
    target_path = os.path.abspath(path) if not os.path.isabs(path) else path    
    return read_file_content(target_path)    

AVAILABLE_TOOLS = {"help_read_file": help_read_file}
python_tools=[help_read_file] # native tool support in .chat() with function calling

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


FILE_PATH_PATTERN = r'[A-Za-z0-9_\-./\\]+\.[A-Za-z0-9]+'


def extract_file_path(text):
    # Try quoted file paths first
    quoted = re.search(r'"([^"]+)"|\'([^\']+)\'', text)
    if quoted:
        return quoted.group(1) or quoted.group(2)

    candidate_paths = re.findall(FILE_PATH_PATTERN, text)
    if candidate_paths:
        return candidate_paths[0]
    return None


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


def check_file_path(user_input):
    local_input = user_input
    temp_file_path = extract_file_path(local_input)
    debug_log(f"check_file_path: file_path: {temp_file_path}")
    if temp_file_path:
        file_content = read_file_content(temp_file_path)
        if file_content is None:                    
            print_msg(f"Could not read the requested file: {temp_file_path}")
        else:
            debug_log(f"check_file_path: file_content is not None")                                                


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
            check_file_path(user_input)
            
            debug_log("process_gui_request: time.time()")
            start_time = time.time()
            debug_log("process_gui_request: agent_workflow()")
            response = agent_workflow(user_input, cancel_event)            
            end_time = time.time()    
            debug_log(f"process_gui_request.Time taken for response: {end_time - start_time:.2f} seconds")
        
            if not cancel_event.is_set():            
                print_msg(f'\nAgent response:\n\n{response}')                
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

    shortcuts_label = tk.Label(root, text='Shortcuts: Ctrl+O = Submit, Ctrl+L = Clear, Ctrl+Q = Exit', anchor='w', fg='gray30', font=('TkDefaultFont', FONT_SIZE))

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

    root.bind('<Control-o>', on_submit)
    root.bind('<Control-O>', on_submit)
    root.bind('<Control-l>', on_clear)
    root.bind('<Control-L>', on_clear)
    root.bind('<Control-q>', lambda event: root.destroy())
    root.bind('<Control-Q>', lambda event: root.destroy())

    exit_button = tk.Button(button_frame, text='Exit', command=root.destroy,
                            font=('TkDefaultFont', FONT_SIZE))    
    exit_button.pack(side='left', padx=(8, 0))

    root.mainloop()


EXIT_COMMAND = "__EXIT_COMMAND__"

def get_multiline_input(prompt_text='-> '):
    """Read multiline user input with Ctrl+O to submit."""
    if PromptSession is None or KeyBindings is None:
        lines = []
        while True:
            if not lines:
                line = input(prompt_text)
            else:
                line = input('-> ')
            if line.lower() == "exit":
                return EXIT_COMMAND
            if not line:
                break
            lines.append(line)
        return "\n".join(lines)

    kb = KeyBindings()

    @kb.add('enter')
    def _(event):
        event.current_buffer.insert_text('\n')

    @kb.add('c-o')
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
    if not user_input.strip():
        debug_log("agent_workflow.No user input provided.")

    debug_log("agent_workflow.Setting messages with system prompt and history")    
    # 1. Build the messages list
    # Setup the ReAct system prompt
    # messages = []    
    messages = system_messages[:] # copy
    # 2. Add context to the conversation (if you want the model to see history)
    for entry in context:
        messages.append({'role': 'user', 'content': entry.get('user_input', '')})
        messages.append({'role': 'assistant', 'content': entry.get('response', '')})

    # 3. Add the current user input
    messages.append({'role': 'user', 'content': user_input})

    full_agent_log = ""
    
    # 4. ReAct Loop (Limit to 5 turns to prevent infinite loops)
    for turn in range(5):
        debug_log(f"agent_workflow.turn = {turn}")
        if cancel_event and cancel_event.is_set():
            break
        
        tool_calls = []  # To store tool calls from the model
        message_content = ''
        try:
            # Use ollama.chat instead of generate            
            response = ollama.chat(
                model=LLM_NAME,
                messages=messages,
                options={
                    'temperature': 1.0,                    
                    'num_ctx': 8192,
                    'stop': ["Observation:", "Observation"] # Force the model to stop here
                },                
                tools=None
            )
            if cancel_event and cancel_event.is_set():
                full_agent_log += '\n[CANCELLED]'
                break   # exit the streaming loop
            # In .chat(), the text is inside chunk['message']['content']
            # Handle text content (Reasoning)
            if 'message' in response and 'content' in response['message']:                
                message_content = response['message']['content']
                has_letters = bool(re.search(r'[a-zA-Z]', message_content))
                debug_log(f"agent_workflow.has_letters = {has_letters}.")            
                has_digits = bool(re.search(r'\d', message_content))
                debug_log(f"agent_workflow.has_digits  = {has_digits}.")                
                if has_letters or has_digits:
                    debug_log(f"agent_workflow.message_content has content.")
                    full_agent_log += f"\n{message_content}\n"                    
                    messages.append({'role': 'assistant', 'content': message_content})                                        
            # Handle tool calls (they arrive in the 'tool_calls' field)
            if 'message' in response and 'tool_calls' in response['message']:
                # We store these to process after the stream finishes
                tool_calls = response['message']['tool_calls']
                debug_log(f"agent_workflow.has tool_calls.")

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
                    debug_log(f"agent_workflow.for call.tool_name = {tool_name}")
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
                        # full_agent_log += f"\n[Tool Observation ({tool_name})] = \n{observation}\n"                        
                        if observation:
                            debug_log(f"agent_workflow.{tool_name}.[Tool.Observation.has content]")
                        else:
                            debug_log(f"agent_workflow.{tool_name}.[Tool.Observation.no content]")
            else:
                # messages.append({'role': 'assistant', 'content': message_content})
                # The following logic is for backward compatibility                
                # and instead outputs Action: ... in text
                # Check if we are done
                if "Answer:" in message_content:
                    debug_log(f"agent_workflow.'Answer:' found in response.")
                    break   # exit the loop ( for _ in range(5) )            
                # Tool Execution Logic
                action_match = re.search(r"Action: (\w+): (.*)", message_content, re.DOTALL)
                debug_log(f"agent_workflow.action_match = {action_match}")
                if action_match:
                    tool_name, tool_input = action_match.groups()
                    debug_log(f"agent_workflow.action_match: tool_name = {tool_name}, tool_input = {tool_input}")
                    # Use your existing TOOLS dictionary
                    # observation = AVAILABLE_TOOLS.get(tool_name, lambda x: "Tool not found")(tool_input)
                    if tool_name in AVAILABLE_TOOLS:
                        observation = AVAILABLE_TOOLS.get(tool_name)(tool_input)
                        obs_text = f"Observation: {observation}"
                        # full_agent_log += f"\n{obs_text}\n"                        
                        messages.append({'role': 'user', 'content': obs_text})
                        if observation:
                            debug_log(f"agent_workflow.[action_match.{tool_name}.Observation has content]")
                        else:
                            debug_log(f"agent_workflow.[action_match.{tool_name}.Observation no content]")
                else:
                    # If the model didn't provide an Action or Answer, stop or prompt it
                    break   # exit the loop ( for _ in range(5) )                            
        except Exception as e:                        
            error_msg = f"Error: {e}"
            debug_log(f"agent_workflow.Exception: {error_msg}")
            full_agent_log += f"\n{error_msg}\n"

    return full_agent_log


def main():
    while True:
        print_msg("\nHow can I help you? ('Ctrl+O' to submit', 'exit'+'Ctrl+O' to quit):")
        user_input = get_multiline_input('-> ')
        
        if user_input == EXIT_COMMAND:
            print_msg("Goodbye!")
            return
        
        # Check if input is empty or starts with 'EXIT' (case-insensitive)
        if not user_input.strip() or user_input.strip().upper().startswith('EXIT'):
            print_msg("Goodbye!")
            return

        print_msg("\nProcessing your request, please wait...")        
        start_time = time.time()       
        response = agent_workflow(user_input)
        end_time = time.time()    
        print_msg(f"\nTime taken for response: {end_time - start_time:.2f} seconds")

        if response is not None:
            print_msg(f"\nAgent response:\n\n {response}")
        else:
            print_msg("Failed to get a response from the Agent.")        
    
        add_to_context(user_input, response)
            
if __name__ == "__main__":
    try:
        gui_main()
    except Exception as e:
        print_msg(f"GUI unavailable, falling back to CLI: {e}")
        main()
