"""Agent 1: Document Intelligence — vision OCR to structured JSON.

Sends an image (photo/scan of a discharge summary, possibly handwritten) to an
OpenRouter vision model and forces a structured extraction matching the
`extracted` object in the shared JSON contract (context.md).

We use plain JSON-in-the-response prompting (not OpenAI tool-calling) because
the free vision models available on OpenRouter are small and inconsistent at
tool-calling. The model's text response is parsed tolerantly and normalized
through Pydantic so the output always conforms to the contract, even if the
model omits or mis-names fields.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from typing import List

from dotenv import load_dotenv

# Load .env so any local config is available even when imported before main.py.
load_dotenv()

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Ollama client (OpenAI-compatible). Routed through the local Ollama daemon
# (http://localhost:11434/v1) to a cloud-hosted 675B Mistral model via the
# Ollama Pro subscription — zero queue times, high accuracy. AsyncOpenAI is
# used (not the sync OpenAI) to preserve the async endpoint in main.py.
# ---------------------------------------------------------------------------

client = AsyncOpenAI(
    api_key="ollama",
    base_url="http://localhost:11434/v1",
)

# Enterprise cloud model exposed by the local Ollama daemon. Vision-capable
# (capabilities: completion, tools, vision), confirmed present via
# `ollama show mistral-large-3:675b-cloud`.
MODEL = "mistral-large-3:675b-cloud"
FALLBACK_MODELS: list[str] = []  # single cloud model — no OpenRouter fallbacks

# Hard ceiling for the whole extraction so a slow call fails fast instead of
# hanging the frontend. Raised to 25s for the heavier 675B reasoning model.
DEADLINE_SECONDS = 25.0

SYSTEM_PROMPT = (
    "You are a clinical document extraction AI. You are shown a photo or scan of "
    "a hospital discharge summary, which may be handwritten or printed. Read it "
    "carefully and extract the structured fields. Respond with ONLY a single "
    "minified JSON object and nothing else — no prose, no markdown fences, no "
    "commentary. Use the exact keys specified. If a field is absent from the "
    "document, use an empty string or an empty array as appropriate."
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
# Output schema (strict JSON contract from context.md)
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
# Core extraction
# ---------------------------------------------------------------------------


def _user_content(data_url: str) -> list:
    """Build the multimodal user message: text prompt + the image."""
    return [
        {"type": "text", "text": EXTRACTION_PROMPT},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]


async def _call_model(model: str, data_url: str, timeout: float = 25.0) -> str | None:
    """Call one vision model. Returns the text content, or None if the model
    returned no usable content (e.g. an empty/error response) so the caller can
    cleanly fall through to the next model. Never raises on a bad response
    shape — those become None rather than a TypeError that aborts the chain.

    `timeout` is a hard per-call ceiling (strict 25s default) so a model that
    stalls fails fast instead of hanging the frontend.
    """
    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(data_url)},
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


def _extract_json_object(text: str) -> dict:
    """Tolerantly pull the first balanced JSON object out of a model response."""
    if not text:
        return {}
    # Strip markdown code fences if present.
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    blob = cleaned[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Last resort: normalize single quotes to double quotes.
        try:
            return json.loads(blob.replace("'", '"'))
        except json.JSONDecodeError:
            return {}


def _downscale(file_bytes: bytes, content_type: str | None, max_side: int = 800) -> tuple[bytes, str]:
    """Downscale an image so its longest edge <= max_side and re-encode as
    lightly-compressed JPEG, which keeps vision inference fast (image-token
    count dominates latency on free models — a 900x1200 sheet took ~67s, the
    same sheet at 600px took ~7s). Returns (resized_bytes, mime). Falls back to
    the raw bytes if Pillow is unavailable or the image cannot be decoded, so
    OCR still works (just slower).
    """
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")  # JPEG requires RGB
        w, h = img.size
        scale = max_side / max(w, h)
        if scale < 1.0:
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        # Slightly reduced JPEG quality cuts upload bytes & processing time;
        # q85 is still plenty sharp for printed/handwritten text OCR.
        img.save(buf, format="JPEG", quality=85, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return file_bytes, content_type or "image/jpeg"


async def extract_discharge(file_bytes: bytes, content_type: str | None) -> dict:
    """Extract structured discharge data from an image and return the
    `extracted` object matching the contract in context.md.

    Args:
        file_bytes: Raw image bytes (JPEG or PNG).
        content_type: MIME type of the image (e.g. "image/jpeg").

    Returns:
        A dict with keys: diagnosis, medications, precautions,
        follow_up_date, warning_signs.
    """
    resized_bytes, mime = _downscale(file_bytes, content_type)
    data_url = f"data:{mime};base64,{base64.b64encode(resized_bytes).decode()}"

    last_error: Exception | None = None
    raw_text: str | None = None

    # Fail-fast: enforce a single cumulative deadline across all model attempts
    # so a queued free-tier model can't hang the frontend. Each call is also
    # capped at its own strict timeout; we stop starting new attempts once the
    # deadline has elapsed.
    start = time.monotonic()
    for model in [MODEL, *FALLBACK_MODELS]:
        elapsed = time.monotonic() - start
        if elapsed >= DEADLINE_SECONDS:
            break  # don't start another slow call past the deadline
        per_call = min(15.0, DEADLINE_SECONDS - elapsed)
        try:
            raw_text = await asyncio.wait_for(
                _call_model(model, data_url, timeout=per_call),
                timeout=per_call + 0.5,
            )
        except asyncio.TimeoutError as exc:
            last_error = exc
            continue
        except Exception as exc:  # noqa: BLE001 — try the next model
            last_error = exc
            continue
        if raw_text and raw_text.strip():
            break

    if not raw_text:
        raise RuntimeError(
            f"Vision extraction failed or timed out within {DEADLINE_SECONDS}s "
            f"deadline for all models. Last error: {last_error!r}"
        )

    raw = _extract_json_object(raw_text)
    # Validate + fill defaults so the contract always holds.
    extracted = Extracted.model_validate(raw)
    return extracted.model_dump()