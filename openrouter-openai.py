import os
from openai import OpenAI, APIStatusError

# 1️⃣  Add a trailing slash to the base URL (optional but common practice)
base_url = "https://openrouter.ai/api/v1/"

api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    raise RuntimeError(
        "Missing OPENROUTER_API_KEY environment variable. "
        "Set it before running: export OPENROUTER_API_KEY=your_key"
    )

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
)

# 2️⃣  Verify your chosen free model. The recommended one is usually just the name,
#     e.g. "openrouter/free". "openai/gpt-oss-20b:free" works, but if you run
#     into a 404 you can fallback to the simpler alias below.
# model = "openai/gpt-oss-20b:free"
model = "openrouter/free"

try:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "What is the meaning of life?",
            }
        ],
    )
    # 3️⃣  Use `.choices[0].message.content` for the Chat Completions API
    print(completion.choices[0].message.content)

    # ──── NEW: Write the response to output/life-meaning.txt ──────────────────────
    import pathlib

    output_dir = pathlib.Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    file_path = output_dir / "life-meaning.txt"
    file_path.write_text(completion.choices[0].message.content, encoding="utf-8")

    print(f"Response written to {file_path.resolve()}")
    # ───────────────────────────────────────────────────────────────────────────────

except APIStatusError as e:
    print(f"OpenRouter API error {e.status_code}: {e}")
    if e.status_code == 401:
        print(
            "Authentication failed. Check OPENROUTER_API_KEY and account/org settings."
        )
    elif e.status_code == 402:
        print(
            "Insufficient credits. Use a free model or a different key with available balance. "
            "If this model is not supported for your account, try another free OpenRouter model."
        )
    else:
        print("Unexpected OpenRouter API error. Check your key, model, and account status.")
except Exception as e:
    print(f"Unexpected error: {e}")