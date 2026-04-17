from multiprocessing import context

import ollama
import json
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
    TKINTER_IMPORT_ERROR = exc
else:
    TKINTER_IMPORT_ERROR = None

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

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:
    PromptSession = None
    KeyBindings = None

# CODE_MODEL = 'qwen2.5-coder:32b-instruct-q3_K_M'
CODE_MODEL = 'qwen2.5-coder:7b'

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
    for path in candidate_paths:
        if os.path.exists(path):
            return path
    return None


DISPLAY_FILE_PATTERNS = [
    r'\b(show|display|print)( me)?( the)?( .+)?( file| content| contents)\b',
]


def is_display_request(text):
    if not isinstance(text, str):
        return False
    text = text.lower()
    return any(re.search(pattern, text) for pattern in DISPLAY_FILE_PATTERNS)


def read_file_contents(path):
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


def format_user_input_for_read(user_input, file_path=None, file_contents=None):
    if file_path and file_contents:
        return (
            f"File path: \n{file_path}"
            f"\n\nFile contents:\n{file_contents}"
            f"\n\nUser question:\n{user_input}"
        )
    else:
        return user_input

def print_boxed_text(text):
    lines = text.splitlines() or ['']
    width = max(len(line) for line in lines)
    border = '+' + '-' * (width + 2) + '+'
    print(border)
    for line in lines:
        print(f"| {line.ljust(width)} |")
    print(border)


def create_file_content_frame(parent, path, content):
    frame = tk.Frame(parent, bd=1, relief='solid')
    label_widget = tk.Label(frame, text=f'File content: {os.path.basename(path)}', anchor='w', font=('TkDefaultFont', 10, 'bold'))
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

    frame.pack(fill='both', padx=8, pady=(0, 8), expand=False)
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


def process_gui_request(user_input, context, request_parent, status_label, file_state, history_canvas=None):
    debug_log(f"DEBUG.process_gui_request: user_input: {user_input}")
    if not user_input.strip():
        status_label.config(text='Please enter a request.')
        return

    request_frame = tk.Frame(request_parent, bd=1, relief='solid', padx=4, pady=4)
    request_frame.pack(fill='x', padx=8, pady=4, expand=False)

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    request_header = tk.Label(request_frame, text=f"Request ({timestamp}): {user_input}", anchor='w', font=('TkDefaultFont', 10, 'bold'))
    request_header.pack(fill='x')

    content_container = tk.Frame(request_frame)
    content_container.pack(fill='both', pady=(4, 4), expand=False)

    request_output_widget = ScrolledText(request_frame, wrap='word', width=110, height=8, state='disabled')
    request_output_widget.pack(fill='both', pady=(4, 8), expand=False)

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
            file_contents = None
            if file_path and (is_file_request(local_input) or is_display_request(local_input)):
                debug_log(f"DEBUG.process_gui_request: last file path before update: {file_state.get('last_file_path')}")
                debug_log(f"DEBUG.process_gui_request: Reading file: {file_path}")
                file_state['last_file_path'] = file_path
                file_contents = read_file_contents(file_path)
                if file_contents is None:
                    request_output_widget.after(0, lambda: append_response_text(f'Could not read the requested file: {file_path}'))
                    return
                debug_log(f"DEBUG.process_gui_request: file_contents is not None")                
                should_display = is_display_request(local_input)               
                local_input = format_user_input_for_read(
                    user_input,
                    file_path,
                    file_contents
                )
            elif is_display_request(local_input):
                request_output_widget.after(0, lambda: append_response_text('No file path detected in your input. Please include one or open a file first.'))
                return

            if should_display and file_contents is not None:
                request_frame.after(0, lambda: create_file_content_frame(content_container, file_path, file_contents))
                request_output_widget.after(0, lambda: append_response_text(f'Displaying file content for {file_path}'))           

            start_time = time.time()               
            
            response = agent_workflow(local_input, context)        
            
            end_time = time.time()    
            debug_log(f"DEBUG.process_gui_request.Time taken for response: {end_time - start_time:.2f} seconds")
        
            context.append({
                'user_input': user_input,
                'response': response,
                'feedback': ''
            })
            request_output_widget.after(0, lambda: append_response_text(f'Agent response:\n{response}'))
        except Exception as exc:
            request_output_widget.after(0, lambda: append_response_text(f'Error: {exc}'))
        finally:
            status_label.after(0, lambda: status_label.config(text='Ready', fg='green', font=('TkDefaultFont', 10, 'bold')))

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

    label = tk.Label(root, text='Enter your request below and click Submit:')
    label.pack(anchor='w', padx=8, pady=(8, 0))

    input_widget = ScrolledText(root, wrap='word', width=110, height=8)
    input_widget.pack(fill='both', padx=8, pady=4, expand=False)

    button_frame = tk.Frame(root)
    button_frame.pack(fill='x', padx=8, pady=4)

    shortcuts_label = tk.Label(root, text='Shortcuts: Ctrl+Enter = Submit, Ctrl+L = Clear, Ctrl+Q = Exit', anchor='w', fg='gray30', font=('TkDefaultFont', 9))
    shortcuts_label.pack(fill='x', padx=8, pady=(0, 4))

    history_frame_container = tk.Frame(root)
    history_frame_container.pack(fill='both', padx=8, pady=(0, 8), expand=True)

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
            process_gui_request(text, gui_main.context, history_frame, status_label, file_state, history_canvas)
            input_widget.delete('1.0', 'end')

    def on_clear(event=None):
        clear_output()

    default_status_font = ('TkDefaultFont', 10, 'bold')
    status_label = tk.Label(root, text='Ready', anchor='w', fg='green', font=default_status_font)
    status_label.pack(fill='x', padx=8, pady=(0, 8))

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


def format_context(context, max_length=6):
    """
    Format and limit the context to the last `max_length` interactions.
    """
    formatted_context = []
    for interaction in context[-max_length:]:
        user_input = interaction.get("user_input", "")
        response = interaction.get("response", "")
        feedback = interaction.get("feedback", "")
        entry = f"User: {user_input}\nAssistant: {response}\nFeedback: {feedback}"
        formatted_context.append(entry)
    return "\n".join(formatted_context)


def agent_workflow(user_input, context=[]):
    # debug_log(f"DEBUG.agent_workflow: user_input: \n{user_input}")
    if not user_input.strip():
        debug_log(f"DEBUG.agent_workflow: No user input provided.")
    last_resp = context[-1].get('response', None) if context else None    
    if last_resp and context:
        context[-1]['feedback'] = user_input   

    formatted_context = format_context(context)    
    code_prompt = f"You are a coding expert. Answer this question:\n\n{user_input}\n\nContext:\n{formatted_context}"
    # code_prompt = f"You are a coding expert. Answer this question: {user_input}"
    code_response = ollama.generate(
        model=CODE_MODEL,
        prompt=code_prompt,
        options={'temperature': 0.0, 'num_ctx': 8192}
    )
    return code_response['response']


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

        if is_file_request(user_input):
            file_path = extract_file_path(user_input)            
            if not file_path:
                file_path = m_file_path
            if not file_path:
                print("No file path detected in your input. Please provide a valid file path.")
                continue            
            else: m_file_path = file_path

            print(f"\nDEBUG: m_file_path: {m_file_path}")
            print(f"DEBUG: Reading file: {file_path}")
            
            file_contents = read_file_contents(file_path)
            if file_contents is not None:
                if is_display_request(user_input):
                    print(f"\nContents of {file_path}:")
                    print_boxed_text(file_contents)
                #user_input = (
                #    f"Read the contents of the file at {file_path} and send it to the LLM:\n\n"
                #    f"File contents:\n{file_contents}"
                #)
                user_input = format_user_input_for_read(
                    user_input,
                    file_path,
                    file_contents
                )
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
    
        context.append({
            "user_input": user_input,
            "response": response,
            "feedback": "" # Left empty; the Router will detect feedback in the next turn
        })
            
if __name__ == "__main__":
    try:
        gui_main()
    except Exception as e:
        print(f"GUI unavailable, falling back to CLI: {e}")
        main()
