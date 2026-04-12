import asyncio
import requests
import time
import json

# Define the base URL for the LLM API
BASE_URL = "http://127.0.0.1:11434"  # Replace with the actual base URL if different
# MODEL_NAME = "llama3.3:latest"
# MODEL_NAME = "alibayram/medgemma:27b"
MODEL_NAME = "MedAIBase/MedGemma1.5:4b"

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

def generate_ollama_response(payload):
    url = f"{BASE_URL}/api/generate"
    headers = {"Content-Type": "application/json"}
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=60) as response:
        response.raise_for_status()
        text_parts = []
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            item = json.loads(line)
            if "response" in item:
                text_parts.append(item["response"])
            if item.get("done"):
                break
    return "".join(text_parts)

async def query_llm(prompt, context=[]):
    # We tell the router what the last response was so it can detect if the user is giving feedback
    last_resp = context[-1].get('response', 'None') if context else 'None'
    
    router_prompt = f"""
    You are a high-speed triage router for a medical AI agent.
    Analyze the user's input and the previous interaction to determine the intent.

    Categories:
    - "FEEDBACK": The user is correcting the previous answer, saying thank you, or providing a critique.
    - "GENERAL": Greetings or casual non-tech chat.

    Previous Assistant Response: {last_resp}
    User input: {prompt}

    Return only a single valid JSON object with exactly one field:
    {{"category": "LABEL"}}
    Do not include any markdown, explanation, code fences, or extra text.
    """

    category = None
    router_data = {
        "model": MODEL_NAME,
        "prompt": router_prompt,
        "max_tokens": 50,
        "temperature": 0.0,
        "format": "json",
    }
    try:
        router_text = generate_ollama_response(router_data)
        if router_text is None:
            print("Router response was None.")
        result = json.loads(router_text)
        category = result.get("category", "GENERAL")
        print(f"\nDEBUG: Router categorized the input as: {category}")
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
    except json.JSONDecodeError as e:
        print(f"Router output was not valid JSON: {e}")
    
    if category and category == 'FEEDBACK':
        context[-1]['feedback'] = prompt if context else {}
    
    formatted_context = format_context(context)
    medical_prompt = f"You are a medical assistant specialized in diabetes. Answer this question:\n\n{prompt}\n\nContext:\n{formatted_context}"
    
    data = {
        "model": MODEL_NAME,
        "prompt": medical_prompt,
        "max_tokens": 500,  # Adjust the number of tokens as needed
        "temperature": 0.2,  # Adjust the temperature for randomness
    }
    try:
        medical_text = generate_ollama_response(data)
        if medical_text is None:
            print("Medical response was None.")
            return None
        return {"response": medical_text}
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None

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
            text = response.get("response", "").strip()
            if text:
                print("Response from LLM:")
                print(text)
            else:
                print("Response from LLM is empty. Check the prompt or model configuration.")
        else:
            print("Failed to get a response from the LLM.")

        context.append({
            "prompt": prompt,
            "response": response,
            "feedback": "" # Left empty; the Router will detect feedback in the next turn
        })

if __name__ == "__main__":
    asyncio.run(main())