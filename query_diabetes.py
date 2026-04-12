import asyncio
import requests
import time
import ollama
import json

# MODEL_NAME = "llama3.3:latest"
# MODEL_NAME = "alibayram/medgemma:27b"
MODEL_NAME = "MedAIBase/MedGemma1.5:4b"

def format_context(context, max_length=6):
    """
    Format and limit the context to the last `max_length` interactions.
    """
    formatted_context = []
    for interaction in context[-max_length:]:
        prompt = interaction.get("prompt", "")
        response = interaction.get("response", "")
        feedback = interaction.get("feedback", "")
        entry = f"User: {prompt}\nAssistant: {response}\nFeedback: {feedback}"
        formatted_context.append(entry)
    return "\n".join(formatted_context)

async def query_llm(prompt, context=[]):
    # We tell the router what the last response was so it can detect if the user is giving feedback
    last_resp = context[-1].get('response', None) if context else None
    print(f"\nDEBUG: Last assistant response for router: {last_resp}")

    router_prompt = f"""
    You are a high-speed triage router for a medical AI agent. 
    Analyze the user's input and the previous interaction to determine the intent.

    Categories:
    - "FEEDBACK": The user is correcting the previous answer, saying thank you, or providing a critique.
    - "GENERAL": Greetings or casual non-tech chat.

    Previous Assistant Response: {last_resp}
    User input: {prompt}
    
    Response format: {{"category": "LABEL"}}
    """

    response = ollama.generate(
        model=MODEL_NAME, 
        prompt=router_prompt, 
        format='json'
    )
    result = json.loads(response['response'])
    category = result.get("category", "GENERAL")
    print(f"\nDEBUG: Router categorized the input as: {category}")

    if category == 'FEEDBACK':
        if last_resp:
            if context:
                context[-1]['feedback'] = prompt
        else:
            print("\nDEBUG: No previous response to attach feedback to.")
            return "Sorry, I couldn't find the previous response to attach your feedback to. Please try again."
            
    formatted_context = format_context(context)
    # medical_prompt = f"You are a medical assistant specialized in diabetes. Answer this question:\n\n{prompt}\n\nContext:\n{formatted_context}"
    medical_prompt = f"You are a medical assistant specialized in diabetes. Answer this question: {prompt}"
    response = ollama.generate(
        model=MODEL_NAME,
        prompt=medical_prompt,
        options={
            'temperature': 0.1,
            'top_p': 0.3
        }
    )
    return response['response']

async def main():
    context = []
    justEntered = True
    while True:
        if justEntered:
            prompt = input("\nHow can I help you? (or type exit to quit): ")
            justEntered = False
        else:
            prompt = input("\nWhat else can I assist you with? (or type exit to quit): ")        
        if prompt.lower() == "exit":
            print("Goodbye!")
            break
        # Record the start time
        start_time = time.time()

        response = await query_llm(prompt, context)

        # Record the end time
        end_time = time.time()
        # Calculate the duration
        duration = end_time - start_time
        print(f"\nTime taken for response: {duration:.2f} seconds\n")

        if response is not None:
            print(f"Assistant response:\n {response}")
        else:
            print("Failed to get a response from the LLM.")

        context.append({
            "prompt": prompt,
            "response": response,
            "feedback": "" # Left empty; the Router will detect feedback in the next turn
        })

if __name__ == "__main__":
    asyncio.run(main())