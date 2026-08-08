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
    "You are a Senior Medical Records Transcription Specialist. You are shown a "
    "photo, scan, or PDF of a hospital discharge summary, which may be neatly "
    "printed, handwritten in illegible doctor cursive, or laid out in a "
    "non-standard clinical format. You are specifically trained on Indian and "
    "Latin medical shorthand and on doctors' cursive handwriting, so you can "
    "read the messy parts that a general OCR would miss.\n\n"
    "MEDICAL SHORTHAND — normalize these abbreviations into clear, human-readable "
    "patient instructions in the extracted output. Do NOT keep the raw "
    "abbreviation; write out its meaning:\n"
    "  OD / QD      → once daily\n"
    "  BD / BID     → twice daily\n"
    "  TDS / TID    → three times daily\n"
    "  QID          → four times daily\n"
    "  HS / QHS     → at bedtime\n"
    "  PRN          → as needed\n"
    "  STAT         → immediately\n"
    "  PC           → after meals\n"
    "  AC           → before meals\n"
    "For example, a medication whose frequency is written as 'BD' or 'BID' must "
    "appear in the output as 'twice daily'; '1 tab OD PC' becomes 'once daily "
    "after meals'. Preserve the original clinical meaning exactly and never "
    "invent fields, doses, or allergies that are not actually on the sheet.\n\n"
    "Respond with ONLY a single minified JSON object and nothing else — no prose, "
    "no markdown fences, no commentary. Use the exact keys specified. If a field "
    "is absent from the document, use an empty string or an empty array as "
    "appropriate."
)

EXTRACTION_PROMPT = (
    "Extract this discharge summary into EXACTLY this JSON schema:\n"
    "{\n"
    '  "diagnosis": "string",\n'
    '  "medications": [{"name":"string","dosage":"string","frequency":"string","duration":"string"}],\n'
    '  "precautions": ["string"],\n'
    '  "follow_up_date": "YYYY-MM-DD or raw text",\n'
    '  "warning_signs": ["string"],\n'
    '  "allergies": ["string"]\n'
    "}\n"
    "The 'allergies' array MUST list every drug/food/substance allergy documented on "
    "the discharge sheet (e.g. [\"Penicillin\", \"Sulfa drugs\", \"NSAIDs\"]). If no "
    "allergies are documented, return an empty array []. Do not infer allergies that "
    "are not written on the sheet.\n"
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
    allergies: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Multimodal request construction
# ---------------------------------------------------------------------------

def _image_content(data_url: str) -> list:
    """Build the multimodal user message for a single image: prompt + image."""
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


def _text_content(text: str) -> list:
    """Build a text-only user message for a text-based PDF (no image)."""
    return [
        {
            "type": "text",
            "text": (
                EXTRACTION_PROMPT
                + "\n\nThe discharge summary text is provided below (extracted "
                "from a text-based PDF). Apply the same medical-shorthand "
                "normalization rules.\n\nDISCHARGE SUMMARY TEXT:\n"
                + text
            ),
        },
    ]


def _pages_content(pages: list) -> list:
    """Build a multimodal user message with one or more rendered page images
    (for scanned / handwritten PDFs). The pages are sent in page order so the
    model can read across the whole document."""
    content: list = [
        {
            "type": "text",
            "text": (
                EXTRACTION_PROMPT
                + "\n\nThe discharge summary spans the following page image(s), "
                "in order. Read every page before extracting."
            ),
        }
    ]
    for img_bytes, mime in pages:
        data_url = f"data:{mime};base64,{base64.b64encode(img_bytes).decode()}"
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    return content


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

async def _call_model(model: str, user_content: list, timeout: float = 25.0) -> str | None:
    """Call one model with a pre-built user message (text and/or images). Returns
    the text content, or None if the model returned no usable content (e.g. an
    empty/error response) so the caller can cleanly fall through to the next
    model. Never raises on a bad response shape — those become None rather than a
    TypeError that aborts the chain.
    """
    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=600,
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
# Native PDF support (pymupdf / fitz)
# ---------------------------------------------------------------------------
#
# A discharge summary often arrives as a PDF rather than a photo. PDFs come in
# two flavours that must be handled differently:
#   1. TEXT-BASED PDFs (electronically generated, e.g. an EHR export): the text
#      is embedded and can be extracted directly — no vision model needed, just
#      send the text to the model with the same extraction prompt.
#   2. SCANNED / HANDWRITTEN PDFs (a photo of each page saved into a PDF): there
#      is no embedded text, so each page is rendered to an image buffer and sent
#      to the vision model exactly like a photo upload.
#
# pymupdf (imported as `fitz`) handles both: `page.get_text()` for (1) and
# `page.get_pixmap()` for (2). It is pure-Python with no system dependency
# (unlike pdf2image, which requires poppler), so it installs cleanly in the
# hackathon environment.

PDF_MIME = "application/pdf"
# A text-based PDF is treated as "has real text" only if it yields at least this
# many whitespace-separated words — a scanned PDF's get_text() returns "" (or a
# couple of stray glyphs), so even a short text PDF clears this comfortably.
PDF_MIN_TEXT_WORDS = 5
# Cap the number of pages rendered for vision OCR so a huge PDF can't blow up
# the image-token budget / latency. The first pages of a discharge summary carry
# the discharge medications, so this is plenty.
PDF_MAX_RENDER_PAGES = 6


def _is_pdf(content_type: str | None) -> bool:
    return (content_type or "").strip().lower() == PDF_MIME


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract embedded text from a PDF, concatenating all pages.

    Returns "" for a scanned PDF (no embedded text). Never raises — a PDF that
    can't be opened yields "" so the caller falls back to rendering pages.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001 — corrupt/encrypted PDF → treat as no text
        return ""
    parts: list[str] = []
    try:
        for page in doc:
            parts.append(page.get_text() or "")
    finally:
        doc.close()
    return "\n".join(parts).strip()


def _render_pdf_pages(
    pdf_bytes: bytes, max_pages: int = PDF_MAX_RENDER_PAGES, max_side: int = 800
) -> list:
    """Render each PDF page to a lightly-compressed JPEG buffer.

    Returns a list of (image_bytes, mime) tuples in page order. Renders at a
    DPI high enough to keep handwritten/printed text legible, then downscales
    so the longest edge <= max_side (same vision-token discipline as photos).
    Returns [] if pymupdf is unavailable or the PDF can't be opened.
    """
    try:
        import fitz  # pymupdf
        import io
        from PIL import Image
    except ImportError:
        return []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001
        return []
    pages: list = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            # 150 DPI keeps small cursive / shorthand legible without huge images.
            pix = page.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            if img.mode != "RGB":
                img = img.convert("RGB")
            w, h = img.size
            scale = max_side / max(w, h)
            if scale < 1.0:
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=False)
            pages.append((buf.getvalue(), "image/jpeg"))
    finally:
        doc.close()
    return pages


async def extract_discharge(file_bytes: bytes, content_type: str | None) -> dict:
    """Extract structured discharge data from an image or PDF and return the
    `extracted` object matching the contract in context.md.

    Args:
        file_bytes: Raw image bytes (JPEG / PNG / WebP) or a PDF document.
        content_type: MIME type of the input (e.g. "image/jpeg",
            "application/pdf").

    Returns:
        A dict with keys: diagnosis, medications, precautions,
        follow_up_date, warning_signs, allergies.

    PDF handling:
        * Text-based PDFs (EHR exports) → embedded text is extracted with
          pymupdf and sent to the model as a text-only message.
        * Scanned / handwritten PDFs → each page is rendered to a JPEG and sent
          to the vision model as a multi-image message, exactly like a photo.
    """
    # Build the user message content once, based on the input type.
    if _is_pdf(content_type):
        user_content, pdf_note = _build_pdf_content(file_bytes)
    else:
        resized_bytes, mime = _downscale(file_bytes, content_type)
        data_url = f"data:{mime};base64,{base64.b64encode(resized_bytes).decode()}"
        user_content = _image_content(data_url)
        pdf_note = "image"

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
                _call_model(model, user_content, timeout=per_call),
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
            f"Extraction failed or timed out within {DEADLINE_SECONDS}s deadline "
            f"for all models (input: {pdf_note}). Last error: {last_error!r}"
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


def _build_pdf_content(pdf_bytes: bytes):
    """Decide whether a PDF is text-based or scanned and build the matching
    user message. Returns (user_content, note) where `note` describes the path
    taken, for error reporting."""
    text = _extract_pdf_text(pdf_bytes)
    if text and len(text.split()) >= PDF_MIN_TEXT_WORDS:
        # Text-based PDF — send the embedded text directly (no rendering).
        return _text_content(text), f"text-based PDF ({len(text.split())} words)"
    # Scanned / handwritten PDF — render pages to images for the vision model.
    pages = _render_pdf_pages(pdf_bytes)
    if not pages:
        raise RuntimeError(
            "PDF could not be processed: no embedded text was found and page "
            "rendering failed (is pymupdf installed and is the PDF valid?)."
        )
    return _pages_content(pages), f"scanned PDF ({len(pages)} page(s) rendered)"