"""Manual LIVE test for Agent 1 vision extraction via OpenRouter.

This is a *manual* script — it makes a real billed OpenRouter vision call
against the newest image in ``uploads/`` and is intentionally NOT collected by
the normal test suite. Run it by hand:

    cd backend && python test_document-extraction.py

It is import-safe: all execution lives in ``main()`` under ``__main__``, so
accidental collection by ``python -m unittest discover`` or ``pytest`` imports
this module without firing any network request or touching the filesystem.
"""

import base64
import mimetypes
import os

from dotenv import load_dotenv
from openai import OpenAI


def main() -> int:
    # ----------------------------------------------------
    # Load environment variables
    # ----------------------------------------------------
    load_dotenv()

    API_KEY = os.getenv("OPENROUTER_API_KEY")
    MODEL = os.getenv("OPENROUTER_MODEL")

    if not API_KEY:
        raise ValueError("OPENROUTER_API_KEY not found in .env")

    if not MODEL:
        raise ValueError("OPENROUTER_MODEL not found in .env")

    print(f"Using model: {MODEL}")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=API_KEY,
    )

    # ----------------------------------------------------
    # Find newest uploaded image
    # ----------------------------------------------------

    UPLOAD_FOLDER = "uploads"

    if not os.path.exists(UPLOAD_FOLDER):
        raise FileNotFoundError("uploads folder not found.")

    allowed_extensions = (".png", ".jpg", ".jpeg", ".webp")

    files = [
        os.path.join(UPLOAD_FOLDER, f)
        for f in os.listdir(UPLOAD_FOLDER)
        if f.lower().endswith(allowed_extensions)
    ]

    if not files:
        raise FileNotFoundError("No image found inside uploads folder.")

    files.sort(key=os.path.getmtime, reverse=True)

    image_path = files[0]

    print(f"Using image: {image_path}")

    # ----------------------------------------------------
    # Convert image to base64
    # ----------------------------------------------------

    mime_type = mimetypes.guess_type(image_path)[0]

    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")

    image_url = f"data:{mime_type};base64,{encoded}"

    # ----------------------------------------------------
    # Prompt
    # ----------------------------------------------------

    PROMPT = """
You are an expert medical document extraction assistant.

Read the uploaded discharge summary carefully.

Extract the following information.

Return ONLY valid JSON.

{
  "patient_name": "",
  "age": "",
  "gender": "",
  "diagnosis": "",
  "medications": [],
  "precautions": [],
  "follow_up_date": "",
  "warning_signs": []
}

Rules:
- Do not explain.
- Do not wrap JSON in markdown.
- If a field is missing, return an empty string or empty array.
"""

    # ----------------------------------------------------
    # Call OpenRouter
    # ----------------------------------------------------

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": PROMPT,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ],
                }
            ],
        )

        print("\n================ FULL RESPONSE ================\n")
        print(response.model_dump_json(indent=2))

        print("\n================ EXTRACTED JSON ================\n")

        if (
            response.choices
            and len(response.choices) > 0
            and response.choices[0].message
            and response.choices[0].message.content
        ):
            print(response.choices[0].message.content)
        else:
            print("No valid response content returned.")

    except Exception as e:
        print("\n================ ERROR ================\n")
        print(type(e).__name__)
        print(e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())