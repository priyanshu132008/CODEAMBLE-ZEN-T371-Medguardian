"""Manual LIVE smoke test for the OpenRouter gateway (Agent 3 / Agent 5 LLM).

This is a *manual* script — it makes a real billed call to OpenRouter and is
intentionally NOT collected by the normal test suite. Run it by hand:

    cd backend && python test_openrouter.py

It is import-safe: the live call only runs under ``__main__``, so accidental
collection by ``python -m unittest discover`` or ``pytest`` imports this module
without firing any network request.
"""

from dotenv import load_dotenv
from openai import OpenAI
import os


def main() -> int:
    load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL")

    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in .env")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly the words: Hello MedGuardian!"
            }
        ],
    )

    print("Model Response:")
    print(response.choices[0].message.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())