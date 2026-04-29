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
    print("failed to import tkinter for GUI mode.")
else:    
    print("Successfully imported tkinter for GUI mode.")

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:
    PromptSession = None
    KeyBindings = None

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain.agents import create_agent

try:
    import speech_recognition as sr
    hasSpeechRecognition = True
except Exception as e:
    hasSpeechRecognition = False
    print(f"SpeechRecognition not installed: {e}")

try:
    from gtts import gTTS
    hasGtts = True
except Exception as e:
    hasGtts = False
    print(f"gTTS not installed: {e}")

try:
    # Using `playsound` (recommended for cross‑platform)
    from playsound import playsound
    hasPlaySound = True
except Exception:
    hasPlaySound = False
    print(f"playsound not installed: {e}")
    """
    # Try the OS default player as a backup
    if sys.platform.startswith('darwin'):      # macOS
        os.system(f"open '{tmp_path}'")
    elif os.name == 'nt':                      # Windows
        os.startfile(tmp_path)
    else:                                      # Linux / BSD
        os.system(f"xdg-open '{tmp_path}'")    
    """

# Updated to use the OpenRouter cloud modely
LLM_NAME = 'openai/gpt-oss-20b:free'
FONT_SIZE = 12
IS_DEBUG = True

file_state = {'last_file_path': None}
context = []
history_frame = None
history_canvas = None
request_frame = None
gui_input_widget = None
gui_output_widget = None
listening_to_mic = False
speech_content = None

system_prompt = (
    "You are a English tutor who is a native American English speaker familiar with teaching conversation and grammar. "
    "You like to make conversation and chat. "
    "You alwasys the user's correct grammar or spelling errors in your responses. "
    "Answer in English and provide detailed explanations for your answers. "
    "Use simple language when explaining complex concepts. "
    "Be patient and kind to students who may not understand things easily. "
    "Be concise, clear, and just direct answer to the questions in your responses. "
    "\nAvailable Tools: \n"
    "- help_read_file: Read content of a file. Input: filename string only.\n"
    "\n**IMPORTANT**: If the user's questions are not related to code or the Available Tools mentioned below, just answer the general question. "
    "\n**IMPORTANT**: When using tool, help_read_file, the exact file path that is given must be used as the Input. "        
)


def print_msg(message):        
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

def has_letters(text):
    return bool(re.search(r'[a-zA-Z]', text))

def has_digits(text):
    return bool(re.search(r'\d', text))


# --- TOOLS ---
@tool("help_read_file")
def help_read_file(path_input: str) -> str:
    """Reads a file using absolute or relative paths."""
    debug_log(f"help_read_file().path_input = {path_input}")
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
python_tools = [help_read_file]


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


def build_gui_request_output_widget():
    global request_frame, gui_output_widget
    request_frame = tk.Frame(history_frame, bd=1, relief='solid', padx=4, pady=4)
    request_frame.pack(fill='x', padx=8, pady=4, expand=False)
    gui_output_widget = tk.Text(request_frame, wrap='word', state='disabled', 
                                    borderwidth=0, highlightthickness=0, 
                                    bg='#f0f0f0', font=('TkDefaultFont', FONT_SIZE))
    gui_output_widget.pack(
        fill='both',  # Essential: fills the space
        expand=True,  # Essential: grows with the window
        side='bottom' # Or wherever you place it
    )


def append_response_text(text):
    if gui_output_widget is None:
        return
    gui_output_widget.configure(state='normal')
    gui_output_widget.insert('end', text + '\n')
    gui_output_widget.see('end')
    gui_output_widget.configure(state='disabled')
    if history_canvas is not None:
        history_canvas.after(50, lambda: history_canvas.yview_moveto(1.0))


def process_gui_request(user_input, status_label, cancel_button, cancel_event):    
    debug_log(f"process_gui_request: user_input: {user_input}")
    if not user_input.strip():
        status_label.config(text='Please enter a request.')
        return    
    text_to_speech(f"the user said {user_input}")  # speak out the user input
    build_gui_request_output_widget()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    request_header = tk.Label(request_frame, text=f"Request ({timestamp}): {user_input}", anchor='w', font=('TkDefaultFont', FONT_SIZE, 'bold'))
    request_header.pack(fill='x')

    append_response_text(f">>> {user_input}")
    append_response_text(">>> Processing your request, please wait...")
    if history_canvas is not None:
        history_canvas.after(100, lambda: history_canvas.yview_moveto(1.0))
    status_label.config(text='Processing...', fg='red', font=('TkDefaultFont', FONT_SIZE, 'bold'))
    cancel_event.clear()
    cancel_button.pack(side='right')
    cancel_button.config(command=lambda: cancel_request(cancel_event, status_label, cancel_button))

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
                add_to_context(user_input, response)
                print_msg(f'\nAgent response:\n\n{response}')
                global speech_content
                if has_letters(response) or has_digits(response):
                    speech_content = response
                else:                    
                    speech_content = "Empty response"
                    print_msg(f'\nspeech_content = {speech_content}')
                text_to_speech(speech_content)  # speaking            
        except Exception as exc:
            if not cancel_event.is_set():
                print_msg(f'\nError: {exc}')                
        finally:
            if not cancel_event.is_set():
                status_label.after(0, lambda: status_label.config(text='Ready', fg='green', font=('TkDefaultFont', FONT_SIZE, 'bold')))
            cancel_button.after(0, lambda: cancel_button.pack_forget())
    threading.Thread(target=worker, daemon=True).start()


def build_history_canvas_frame(w_root):
    global history_frame, history_canvas    
    history_frame_container = tk.Frame(w_root)
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

    output_label = tk.Label(history_frame, text='Output:', font=('TkDefaultFont', FONT_SIZE, 'bold'))
    output_label.pack(anchor='w')


def build_gui_input_widget(w_root):
    global gui_input_widget
    input_label = tk.Label(w_root, text='Enter your request and click Submit:',
                           font=('TkDefaultFont', FONT_SIZE, 'bold'))  
    input_label.pack(anchor='w', padx=8, pady=(8, 0))
    gui_input_widget = ScrolledText(w_root, wrap='word', width=110, height=8, font=('TkDefaultFont', FONT_SIZE))
    gui_input_widget.pack(fill='both', padx=8, pady=4, expand=False)    


# -------------  STT Helper ------------------------------------------
def start_listening_to_mic():
    """
    Record a clip from the default mic
    and return the transcribed text (or an error message).
    """
    recognizer = sr.Recognizer()
    # 1. Grab a short chunk from the microphone
    with sr.Microphone() as source:
        print_msg("Mic active – please speak…")
        # Optional: adjust for ambient noise
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        # "listening_to_mic" is global variable
        while listening_to_mic:            
            try:
                # audio = recognizer.listen(source, timeout=10, phrase_time_limit=10)
                audio = recognizer.listen(source, timeout=5)
                # 2. Convert to text using Google Web Speech (free, no API key)
                text = recognizer.recognize_google(audio)
                gui_input_widget.insert('end', f"\n{text}")
            except sr.WaitTimeoutError:
                continue                    
            except sr.UnknownValueError:
                continue
            except sr.RequestError as e:
                continue
            except Exception as e:
                print_msg(f"start_listening_to_mic.Unexpected error: {e}")
                break
        print_msg("start_listening_to_mic.Stopped listening.")

# ----  You only need to run once to install the runtime ----
# pip install gtts  # (and optionally pip install playsound)
# ==============================================================
#  Text‑to‑Speech helper – text_to_speech(text, lang='en')
# ==============================================================
def text_to_speech(text, lang='en', temp_file=None):
    """
    Convert *text* to speech and play it immediately.
    
    Parameters
    ----------
    text : str
        The string you want spoken.
    lang : str, optional
        ISO‑639‑1 language code (default='en').
        gTTS supports many languages – see https://gtts.readthedocs.io/en/latest/module.html
    temp_file : str, optional
        Path to store the temporary `.mp3` file.  
        If omitted, an in‑memory temporary file is used.

    Returns
    -------
    tmp_path : str
        Path to the generated audio file (useful if you want to keep it).
    """
    # 1️⃣ Make sure the library is available
    if not hasGtts or not hasPlaySound:
        return None
    # 2️⃣ Create the TTS object
    tts = gTTS(text=text, lang=lang)
    # 3️⃣ Save to a temporary file (or user‑supplied path)
    if temp_file is None:
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix='.mp3')
        os.close(fd)    # close the FD – gTTS will open it
    else:
        tmp_path = temp_file
    # 4️⃣ Play the file (fallback to system player)
    try:
        tts.save(tmp_path)
        # Using `playsound` (recommended for cross‑platform)
        playsound(tmp_path)
    except Exception as e:
        print_msg(f"text_to_speech.Exception: {e}")

    return tmp_path


def gui_main():
    if tk is None or ScrolledText is None:
        print('gui_main.tkinter is not available; falling back to CLI.')
        prompt_tkinter_install_help()
        main()
        return

    try:
        root = tk.Tk()
    except Exception as exc:
        print(f'gui_main.GUI startup failed ({exc}); falling back to CLI.')
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

    build_history_canvas_frame(root)
    build_gui_input_widget(root)    

    shortcuts_label = tk.Label(root, text='Shortcuts: Ctrl+O = Submit, Ctrl+L = Clear, Ctrl+Q = Exit', anchor='w', fg='gray30', font=('TkDefaultFont', FONT_SIZE))    
    shortcuts_label.pack(fill='x', padx=8, pady=(0, 4))    
    button_frame = tk.Frame(root)
    button_frame.pack(fill='x', padx=8, pady=4)
    
    def clear_output():
        for child in history_frame.winfo_children():
            child.destroy()
        output_label = tk.Label(history_frame, text='Output:')
        output_label.pack(anchor='w')

    def on_submit(event=None):
        text = gui_input_widget.get('1.0', 'end').strip()
        if text:
            process_gui_request(text, status_label, cancel_button, cancel_event)
            gui_input_widget.delete('1.0', 'end')        

    def browse_file():
        if filedialog is None:
            return
        path = filedialog.askopenfilename(initialdir=os.getcwd(), title='Select a file')
        if path:
            if gui_input_widget.get('1.0', 'end').strip():
                gui_input_widget.insert('end', ' ' + path)
            else:
                gui_input_widget.insert('end', path)

    def on_clear(event=None):
        clear_output()

    def on_mic():        
        if not hasSpeechRecognition:
            print_msg(f"SpeechRecognition not installed: {e}")
            return
        global listening_to_mic
        listening_to_mic = not listening_to_mic
        if listening_to_mic:
            mic_button.config(bg='red')
            mic_thread = threading.Thread(target=start_listening_to_mic, daemon=True)
            mic_thread.start()
            print_msg("gui_main.on_mic.Mic button pressed – started listening.")
        else:
            mic_button.config(bg=original_mic_bg)            
            print_msg("gui_main.on_mic.Mic button pressed – stopping listening.")
        
    def on_speak():    
        if not speech_content:
            print_msg("gui_main.on_speak.Nothing to say, speech_content is empty.")
            return
        # Speak it out loud
        try:
            text_to_speech(speech_content)
        except Exception as exc:
            print_msg(f"gui_main.on_speak.Error in TTS: {exc}")

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

    submit_button = tk.Button(button_frame, text='Submit', command=on_submit,
                              font=('TkDefaultFont', FONT_SIZE))
    submit_button.pack(side='left')

    browse_button = tk.Button(button_frame, text='Browse File', command=browse_file,
                              font=('TkDefaultFont', FONT_SIZE))
    browse_button.pack(side='left', padx=(8, 0))

    clear_button = tk.Button(button_frame, text='Clear Output', command=clear_output,
                             font=('TkDefaultFont', FONT_SIZE))
    clear_button.pack(side='left', padx=(8, 0))

    exit_button = tk.Button(button_frame, text='Exit', command=root.destroy,
                            font=('TkDefaultFont', FONT_SIZE))    
    exit_button.pack(side='left', padx=(8, 0))

    speak_button = tk.Button(
        button_frame,
        text='Speak',
        command=on_speak,
        font=('TkDefaultFont', FONT_SIZE)
    )
    speak_button.pack(side='right', padx=(8, 0))

    mic_button = tk.Button(
            button_frame,            
            text="Mic",
            command=on_mic,
            font=('TkDefaultFont', FONT_SIZE),
            compound=tk.LEFT,  # show image/text together if you use both
        )
    mic_button.pack(side='right', padx=(8, 0))
    # Remember the original bg colour (works on Windows, macOS, Linux)
    original_mic_bg = mic_button.cget('bg')   # <-- store it now!

    root.bind('<Control-o>', on_submit)
    root.bind('<Control-O>', on_submit)
    root.bind('<Control-l>', on_clear)
    root.bind('<Control-L>', on_clear)
    root.bind('<Control-q>', lambda event: root.destroy())
    root.bind('<Control-Q>', lambda event: root.destroy())

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
    """
    Uses LangChain to orchestrate the ReAct agent with Ollama.
    """
    debug_log("agent_workflow: Started agent_workflow")
    if not user_input.strip():
        debug_log("agent_workflow: No user input provided.")

    debug_log("agent_workflow: Setting messages with system prompt and history")    
    # 1. Prepare the History (Context)
    # Add history
    # ------------------------------------------------------------------
    # 1️⃣ Build the full message list (system prompt + chat history)
    # ------------------------------------------------------------------
    # Start with the system prompt (already defined as a string above)
    messages = []
    # Append every past user/assistant turn in order
    for entry in context:
        messages.append(("user", entry["user_input"]))
        messages.append(("assistant", entry["response"]))
    # Finally, add the current user input
    messages.append(("user", user_input))

    # 2. Initialize LangChain Components
    debug_log("agent_workflow: ChatOpenAI() for OpenRouter")
    llm = ChatOpenAI(
        model=LLM_NAME,
        temperature=1.0,
        # OpenRouter specific configuration
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=os.getenv("OPENROUTER_API_KEY"),
        streaming=False,
    )
    # debug_log(f"{llm.invoke('Hello, who are you?')}")

    full_agent_log = ""
        
    try:    
        # 4. Create the Agent        
        debug_log("agent_workflow: create_agent()")
        agent = create_agent(model=llm, tools=python_tools, system_prompt=system_prompt)
    except Exception as e:
        error_msg = f"agent_workflow.create_agent().Exception error: {str(e)}"
        debug_log(f"agent_workflow.create_agent.Exception")
        full_agent_log += f"\n{error_msg}\n"
        return full_agent_log
  
    # 5. Execute the Agent        
    debug_log("agent_workflow: agent.invoke()")
    try:        
        # messages_0 = [("user", user_input)]
        result = agent.invoke(input={"messages": messages}, config={"recursion_limit": 50})
        # This is the right calling format of invoke()
        #result = agent.invoke(
        #    input={"messages": [("user", "read output/generated_code.py and run it")]},
        #    config={"recursion_limit": 50}
        #)
        full_agent_log = result["messages"][-1].content    
    except Exception as e:
        error_msg = f"agent_workflow.agent.invoke().Exception: {str(e)}"
        debug_log("agent_workflow.run agent.invoke().Exception")
        full_agent_log += f"\n{error_msg}\n"
        return full_agent_log

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

        global speech_content
        if has_letters(response) or has_digits(response):
            speech_content = response
        else:                    
            speech_content = "Empty response"
            print_msg(f'\nspeech_content = {speech_content}')
        text_to_speech(speech_content)  # speaking
    
            
if __name__ == "__main__":
    try:
        gui_main()
    except Exception as e:
        print_msg(f"GUI unavailable, falling back to CLI: {e}")
        main()
