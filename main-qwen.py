import asyncio
import os
from autogen_ext.models.ollama import OllamaChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor

async def main():
    try:
        # 1. Connection (Using the correct .1 address)
        model_client = OllamaChatCompletionClient(  # Updated to use OllamaChatCompletionClient
            model="qwen2.5-coder:32b-instruct-q3_K_M",
            base_url="http://127.0.0.1:11434"
            # or base_url="http://127.0.0.1"
        )

        # 2. Setup the Executor and the specialized Agent
        os.makedirs("output", exist_ok=True)
        executor = LocalCommandLineCodeExecutor(work_dir="output", timeout=60)

        # In 0.4+, we use CodeExecutorAgent instead of UserProxyAgent for auto-running
        code_executor_agent = CodeExecutorAgent(
            name="code_executor_agent",
            code_executor=executor
        )

        # 3. Setup the Brain
        assistant = AssistantAgent(
            name="assistant",
            model_client=model_client,
            system_message="You are a senior coder. Provide only the Python code for the task in a code block. Do not ask for user input at runtime."
            # system_message="You are a senior coder. Provide only the Python code for the task in a code block"
        )

        print("--- 1. Assistant is generating code... ---")
        # task = "Write a Python script for a random password generator with a fixed default length of 12 and print the result"
        task = "Write a Python script for a random password generator with a fixed default length of 12 and print the result without requiring any interactive input."
        assistant_run = await assistant.run(task=task)
        assistant_msg = assistant_run.messages[-1]
        print(f"\n[ASSISTANT]:\n{assistant_msg.content}")

        # Extract the code from the message
        code_content = assistant_msg.content
        if "```python" in code_content:
            start = code_content.find("```python") + len("```python")
            end = code_content.find("```", start)
            if end == -1:
                end = len(code_content)
            code = code_content[start:end].strip()
        else:
            code = code_content.strip()

        # Write the generated code to output folder
        code_file_path = os.path.join("output", "generated_code.py")
        with open(code_file_path, "w") as f:
            f.write(code)
        print(f"Generated code written to {code_file_path}")

        print("\n--- 2. Executor is running the code automatically... ---")
        # We pass the assistant's message to the executor agent
        try:
            executor_run = await code_executor_agent.run(task=assistant_msg.content)
        except Exception as e:
            print(f"Executor error: {e}")
        else:
            # Print the terminal output from the script
            for msg in executor_run.messages:
                print(f"\n[EXECUTION LOG]:\n{msg.content}")
    except Exception as e:
        print(f"Main error: {e}")

if __name__ == "__main__":
    asyncio.run(main())