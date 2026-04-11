import asyncio
import requests
import time

# Define the base URL for the LLM API
BASE_URL = "http://127.0.0.1:11434"  # Replace with the actual base URL if different
MODEL_NAME = "llama3.3:latest"

async def query_llm(prompt):
    url = f"{BASE_URL}/v1/completions"
    headers = {
        "Content-Type": "application/json",
    }
    data = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "max_tokens": 500,  # Adjust the number of tokens as needed
        "temperature": 0.7,  # Adjust the temperature for randomness
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None

async def main():
    # Prompt the user for input
    prompt = input("Enter your query about diabetes or related documents: ")

    # Record the start time
    start_time = time.time()

    response = await query_llm(prompt)

    # Record the end time
    end_time = time.time()
    
    # Calculate the duration
    duration = end_time - start_time
    print(f"Time taken for response: {duration:.2f} seconds\n")

    if response is not None:
        # print("Raw Response from LLM:")
        # print(response)  # Print raw response for debugging

        # Check if the expected keys exist in the response
        choices = response.get("choices", [])
        if choices and "text" in choices[0]:
            text = choices[0]["text"].strip()
            if text:
                print("Response from LLM:")
                print(text)
            else:
                print("Response from LLM is empty. Check the prompt or model configuration.")
        else:
            print("Unexpected response structure. Could not find 'choices' or 'text'.")
    else:
        print("Failed to get a response from the LLM.")

if __name__ == "__main__":
    asyncio.run(main())