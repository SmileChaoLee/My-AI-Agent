import asyncio
from autogen_ext.models.ollama import OllamaChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent

async def main():
    # 1. Connection (using the IP that worked for you)
    model_client = OllamaChatCompletionClient(
        model="llama3.2:latest",
        base_url="http://127.0.0.1"
    )

    # 2. Define the Agents
    assistant = AssistantAgent(
        name="assistant",
        model_client=model_client,
        system_message="You are a senior coder. Provide a full Python script for the task."
    )

    # Note: UserProxyAgent by default handles code execution if it sees code blocks
    user_proxy = UserProxyAgent(name="user_proxy")

    print("--- 1. Assistant is generating code... ---")
    
    # Manually trigger the assistant first
    task = "Write a Python script for a random password generator."
    assistant_run = await assistant.run(task=task)
    
    # Get the code written by the assistant
    assistant_msg = assistant_run.messages[-1]
    print(f"\n[ASSISTANT]:\n{assistant_msg.content}")

    # 3. Manually trigger the Proxy to execute that code
    print("\n--- 2. User Proxy is executing the code... ---")
    proxy_run = await user_proxy.run(task=assistant_msg.content)
    
    # Print the result of the execution
    for msg in proxy_run.messages:
        if msg.source == "user_proxy":
            print(f"\n[EXECUTION RESULT]:\n{msg.content}")

if __name__ == "__main__":
    asyncio.run(main())
