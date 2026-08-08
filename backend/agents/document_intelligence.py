"""Agent 1: Document Intelligence — vision OCR to structured JSON.

Sends an image (photo/scan of a discharge summary, possibly handwritten) to an
Ollama vision model and forces a structured extraction matching the
`extracted` object in the shared JSON contract (context.md).

We use plain JSON-in-the-response prompting (not OpenAI tool-calling) because
the available vision models are inconsistent at tool-calling. The model's text
response is parsed tolerantly and normalized through Pydantic so the output
always conforms to the contract, even if the model omits or mis-names fields.

The active Ollama model and timeout are controlled entirely through environment
variables so the same code can run with different models on different machines.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from typing import List

from dotenv import load_dotenv

# Load .env so local configuration is available even when this module is
# imported before main.py.
load_dotenv()

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------
# Ollama exposes an OpenAI-compatible API locally.
#
# The actual model is selected through OLLAMA_MODEL in .env.
#
# Example on the development machine:
#   OLLAMA_MODEL=gemma3:4b
#
# Example on the presentation machine:
#   OLLAMA_MODEL=mistral-large-3:675b-cloud
# ---------------------------------------------------------------------------

client = AsyncOpenAI(
    api_key="ollama",
    base_url=os.getenv(
        "OLLAMA_BASE_URL",
        "http://localhost:11434/v1",
    ),
)

# Model is intentionally configuration-driven.
MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")

# No additional fallback models currently configured.
FALLBACK_MODELS: list[str] = []


# ---------------------------------------------------------------------------
# Extraction timeout
# ---------------------------------------------------------------------------
# This is the maximum cumulative amount of time allowed for the extraction.
#
# Configure through:
#
#   OLLAMA_TIMEOUT_SECONDS=180
#
# The per-call timeout below is derived from this value. There is intentionally
# no hidden 15-second cap because local CPU vision models may require longer.
# ---------------------------------------------------------------------------

DEADLINE_SECONDS = float(
    os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")
)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a clinical document extraction AI. You are shown a photo or scan "
    "of a hospital discharge summary, which may be handwritten or printed. "
    "Read it carefully and extract the structured fields. Respond with ONLY "
    "a single minified JSON object and nothing else — no prose, no markdown "
    "fences, no commentary. Use the exact keys specified. If a field is "
    "absent from the document, use an empty string or an empty array as "
    "appropriate."
)

EXTRACTION_PROMPT = (
    "Extract this discharge summary into EXACTLY this JSON schema:\n"
    "{\n"
    '  "diagnosis": "string",\n'
    '  "medications": [{"name":"string","dosage":"string","frequency":"string","duration":"string"}],\n'
    '  "precautions": ["string"],\n'
    '  "follow_up_date": "YYYY-MM-DD or raw text",\n'
    '  "warning_signs": ["string"]\n'
    "}\n"
    "Return ONLY the JSON object."
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------
# Strict JSON contract from context.md.
# ---------------------------------------------------------------------------

class Medication(BaseModel):
    name: str = ""
    dosage: str = ""
    frequency: str = ""
    duration: str = ""


class Extracted(BaseModel):
    diagnosis: str = ""
    medications: List[Medication] = Field(default_factory=list)
    precautions: List[str] = Field(default_factory=list)
    follow_up_date: str = ""
    warning_signs: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Multimodal request construction
# ---------------------------------------------------------------------------

def _user_content(data_url: str) -> list:
    """Build the multimodal user message containing the prompt and image."""
    return [
        {
            "type": "text",
            "text": EXTRACTION_PROMPT,
        },
        {
            "type": "image_url",
            "image_url": {
                "url": data_url,
            },
        },
    ]


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

async def _call_model(
    model: str,
    data_url: str,
    timeout: float,
) -> str | None:
    """Call one vision model.

    Returns the model's text response, or None if no usable content was
    returned.

    The timeout is supplied by the caller and ultimately comes from the
    OLLAMA_TIMEOUT_SECONDS environment variable.
    """

    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": _user_content(data_url),
            },
        ],
        temperature=0.0,
        max_tokens=300,
        timeout=timeout,
    )

    choices = getattr(completion, "choices", None) or []

    if not choices:
        return None

    message = choices[0].message
    content = getattr(message, "content", None)

    return content or None


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json_object(text: str) -> dict:
    """Tolerantly pull the first JSON object out of a model response."""

    if not text:
        return {}

    # Strip markdown code fences if present.
    cleaned = re.sub(
        r"```(?:json)?",
        "",
        text,
    ).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end < start:
        return {}

    blob = cleaned[start : end + 1]

    try:
        return json.loads(blob)

    except json.JSONDecodeError:
        # Last-resort compatibility for models that return single quotes.
        try:
            return json.loads(blob.replace("'", '"'))
        except json.JSONDecodeError:
            return {}


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

def _downscale(
    file_bytes: bytes,
    content_type: str | None,
    max_side: int = 800,
) -> tuple[bytes, str]:
    """Downscale an image and re-encode it as JPEG.

    Keeping the longest edge below max_side reduces image-token count and
    therefore improves vision inference latency.

    Falls back to the original bytes if Pillow is unavailable or the image
    cannot be decoded.
    """

    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(file_bytes))

        if img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size

        scale = max_side / max(width, height)

        if scale < 1.0:
            new_size = (
                max(1, int(width * scale)),
                max(1, int(height * scale)),
            )

            img = img.resize(
                new_size,
                Image.LANCZOS,
            )

        buffer = io.BytesIO()

        img.save(
            buffer,
            format="JPEG",
            quality=85,
            optimize=False,
        )

        return buffer.getvalue(), "image/jpeg"

    except Exception:
        return (
            file_bytes,
            content_type or "image/jpeg",
        )


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

async def extract_discharge(
    file_bytes: bytes,
    content_type: str | None,
) -> dict:
    """Extract structured discharge data from an image.

    Returns the `extracted` object matching the contract in context.md.

    Args:
        file_bytes:
            Raw image bytes.

        content_type:
            MIME type of the image, for example image/jpeg or image/png.

    Returns:
        A dictionary containing:

        - diagnosis
        - medications
        - precautions
        - follow_up_date
        - warning_signs
    """

    # ---------------------------------------------------------------
    # Prepare image
    # ---------------------------------------------------------------

    resized_bytes, mime = _downscale(
        file_bytes,
        content_type,
    )

    data_url = (
        f"data:{mime};base64,"
        f"{base64.b64encode(resized_bytes).decode()}"
    )

    # ---------------------------------------------------------------
    # Model attempts
    # ---------------------------------------------------------------

    last_error: Exception | None = None
    raw_text: str | None = None

    start = time.monotonic()

    models = [
        MODEL,
        *FALLBACK_MODELS,
    ]

    for model in models:

        elapsed = time.monotonic() - start

        if elapsed >= DEADLINE_SECONDS:
            break

        # IMPORTANT:
        # Do not impose a hidden 15-second limit.
        #
        # The remaining time comes directly from
        # OLLAMA_TIMEOUT_SECONDS in the .env file.
        per_call = DEADLINE_SECONDS - elapsed

        try:
            raw_text = await asyncio.wait_for(
                _call_model(
                    model,
                    data_url,
                    timeout=per_call,
                ),
                timeout=per_call + 0.5,
            )

        except asyncio.TimeoutError as exc:
            last_error = exc
            continue

        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        if raw_text and raw_text.strip():
            break

    # ---------------------------------------------------------------
    # Handle extraction failure
    # ---------------------------------------------------------------

    if not raw_text:
        raise RuntimeError(
            f"Vision extraction failed or timed out within "
            f"{DEADLINE_SECONDS}s deadline for all models. "
            f"Last error: {last_error!r}"
        )

    # ---------------------------------------------------------------
    # Parse model response
    # ---------------------------------------------------------------

    raw = _extract_json_object(raw_text)

    # ---------------------------------------------------------------
    # Validate structured output
    # ---------------------------------------------------------------

    extracted = Extracted.model_validate(raw)

    return extracted.model_dump()