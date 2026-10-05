import os
from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()

token = os.getenv("HF_TOKEN")

if not token:
    print("Hugging Face token not found!")
    exit()

client = InferenceClient(
    api_key=token
)

try:
    print("Connecting to Hugging Face...")

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {
                "role": "user",
                "content": "Hello Jarvis, explain Python in simple English."
            }
        ],
        max_tokens=150
    )

    answer = response.choices[0].message.content

    print("\nJarvis:", answer)

except Exception as e:
    print("Error:", e)