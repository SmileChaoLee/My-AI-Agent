import ollama
import json
import time

MEDICAL_MODEL = 'llama3.2:latest'
CODE_MODEL = 'qwen2.5-coder:32b-instruct-q3_K_M'
TECHNOLOGY_MODEL = 'qwen2.5-coder:7b'
GENERAL_MODEL = 'llama3.2:latest'
last_model_used = [MEDICAL_MODEL]

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
    # 1. THE ROUTER
    # We tell the router what the last response was so it can detect if the user is giving feedback
    last_resp = context[-1].get('response', 'None') if context else 'None'
    
    router_prompt = f"""
    You are a high-speed triage router for a medical AI agent. 
    Analyze the user's input and the previous interaction to determine the intent.

    Categories:
    - "MEDICAL": Questions about diabetes, insulin, or health.
    - "CODE": Specific programming tasks, debugging, or scripts.
    - "TECHNOLOGY": Explaining how things work, hardware specs, or tech trends.
    - "FEEDBACK": The user is correcting the previous answer, saying thank you, or providing a critique.
    - "GENERAL": Greetings or casual non-tech chat.

    Previous Assistant Response: {last_resp}
    User input: {user_input}
    
    Response format: {{"category": "LABEL"}}
    """

    response = ollama.generate(
        model='llama3.2:latest', 
        prompt=router_prompt, 
        format='json'
    )

    result = json.loads(response['response'])
    category = result.get("category", "GENERAL")
    formatted_context = format_context(context)

    # 2. THE HAND-OFF LOGIC
    if category == 'FEEDBACK':
        print(f"DEBUG: Recognized as Feedback | Category: {category}\n")
        # feedback_prompt = f"The user is providing feedback on your last response. Acknowledge it politely and briefly.\n\nLast Response: {last_resp}\nUser Feedback: {user_input}"
        # feedback_response = ollama.generate(model=last_model_used[0], prompt=feedback_prompt)
        # return feedback_response['response']
        if last_resp:
            if last_model_used[0] == MEDICAL_MODEL:
                category = 'MEDICAL'
            elif last_model_used[0] == CODE_MODEL:
                category = 'CODE'
            elif last_model_used[0] == TECHNOLOGY_MODEL:
                category = 'TECHNOLOGY'
            else:
                # last_model_used[0] == GENERAL_MODEL:
                category = 'GENERAL'
        else:
            return "No question provided before"
    
    if category == 'MEDICAL':
        last_model_used[0] = MEDICAL_MODEL
        print(f"DEBUG: Routed to Medical Expert (Llama 3.2) | Category: {category}\n")
        medical_prompt = f"You are a medical assistant specialized in diabetes. Answer this question:\n\n{user_input}\n\nContext:\n{formatted_context}"
        medical_response = ollama.generate(model=last_model_used[0], prompt=medical_prompt, options={'temperature': 0.1, 'top_p': 0.3})    
        return medical_response['response']
    
    elif category == 'CODE':
        last_model_used[0] = CODE_MODEL
        print(f"DEBUG: Routed to Coding Expert (Qwen 2.5) | Category: {category}\n")
        code_prompt = f"You are a coding expert. Answer this question:\n\n{user_input}\n\nContext:\n{formatted_context}"
        code_response = ollama.generate(model=last_model_used[0], prompt=code_prompt, options={'temperature': 0.0, 'num_ctx': 8192})
        return code_response['response']
    
    elif category == 'TECHNOLOGY':
        last_model_used[0] = TECHNOLOGY_MODEL
        print(f"DEBUG: Routed to Technology Expert (Qwen 2.5) | Category: {category}\n")
        tech_prompt = f"You are a technology expert. Explain this concept clearly:\n\n{user_input}\n\nContext:\n{formatted_context}"
        tech_response = ollama.generate(model=last_model_used[0], prompt=tech_prompt, options={'temperature': 0.4, 'top_p': 0.9})
        return tech_response['response']
    
    else:
        last_model_used[0] = GENERAL_MODEL
        print(f"DEBUG: Handling General Chat with Llama 3.2 | Category: {category}")
        general_prompt = f"You are a friendly, helpful assistant. Chat naturally:\n\n{user_input}\n\nContext:\n{formatted_context}"
        general_response = ollama.generate(model=last_model_used[0], prompt=general_prompt, options={'temperature': 0.8, 'top_p': 0.9})
        return general_response['response']

def main():
    context = []
    justEntered = True
    while True:
        if justEntered:
            user_input = input("How can I help you? (or type exit to quit): ")
            justEntered = False
        else:
            user_input = input("What else can I assist you with? (or type exit to quit): ")
        
        if user_input.lower() == "exit":
            print("Goodbye!")
            break
        
        print("\nProcessing your request, please wait...\n")        
        start_time = time.time()    
        
        # FIX 1: Pass the context into the function!
        response = agent_workflow(user_input, context)
        
        end_time = time.time()    
        print(f"Time taken for response: {end_time - start_time:.2f} seconds\n")
        print("Response from Agent Workflow:")
        print(response)

        # FIX 2: Instead of asking for feedback via input(), we just save the interaction.
        # If the user wants to give feedback, they will do it in the NEXT user_input turn.
        context.append({
            "user_input": user_input,
            "response": response,
            "feedback": "" # Left empty; the Router will detect feedback in the next turn
        })
        
        # Optional: print current context to see it working
        # print(f"\nCurrent context size: {len(context)} interactions")

if __name__ == "__main__":
    main()
