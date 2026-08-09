"""Auto-Claim & Insurance Justification Engine.

Converts an extracted discharge summary contract into a standardized insurance
claim justification dossier, eliminating TPA (Third-Party Administrator)
discharge delays.

Pipeline:
  1. The clinical context is scrubbed through the Privacy Sandbox
     (`PIIScrubber.anonymize_payload`) before it reaches the LLM.
  2. A Certified Medical Billing & Coding Specialist persona (via OpenRouter,
     Anthropic Claude 3.5 Sonnet, falling back to Google Gemini 1.5 Pro)
     evaluates the diagnosis + medications and returns a strict JSON dossier
     via OpenAI tool-calling:
       - icd10_codes            : matched primary/secondary ICD-10 codes
       - medical_necessity_brief: 3-bullet clinical rationale
       - claim_summary          : billing line items + coverage justification
  3. A lightweight HTML formatter renders the dossier as a Claim Summary
     Report for the hospital UI.
  4. A transparent copy of the claim status is emailed to the patient via
     Resend (graceful terminal-print fallback if Resend is unavailable).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List

from dotenv import load_dotenv

# Load .env so OPENROUTER_API_KEY / RESEND_API_KEY are available even when
# this module is imported before main.py (e.g. in tests). Idempotent.
load_dotenv()

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

import resend

# Bind the Resend key explicitly (the SDK binds it at its own import time; this
# guarantees it is set regardless of import order). No mock/test mode — if the
# key is present, resend.Emails.send() fires for real.
_resend_key = os.getenv("RESEND_API_KEY")
if _resend_key:
    resend.api_key = _resend_key

from agents.privacy_sandbox import PIIScrubber
from agents.compliance_guard import collect_explicit_names, prepare_clinical_payload

# ---------------------------------------------------------------------------
# OpenRouter client (separate, dedicated instance for this engine)
# ---------------------------------------------------------------------------

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

# Primary model: a fast free JSON-producing model via OpenRouter. The free
# tiers are inconsistent at OpenAI function-calling, so we use plain
# JSON-in-content prompting and parse the output ourselves (see below).
# These slugs were verified live against OpenRouter (2026-08-08) — the older
# `:free` Llama/Gemini-1.5/Gemma-2 slugs have been retired and now 404.
#
# gemma-4-26b-a4b-it is a 4B-active MoE: ~5s per dossier vs ~64s for
# gpt-oss-20b / ~30s+ for the 120B Nemotron, so it is the primary to keep the
# /api/claim/generate request well under the HTTP client timeout. The larger,
# higher-quality Nemotron models stay as fallbacks for when the primary is
# unavailable / rate-limited / returns unparseable output.
MODEL = "google/gemma-4-26b-a4b-it:free"
# Fallback models tried in order. A per-model timeout (MODEL_TIMEOUT_S) caps
# each attempt so a single slow/hanging model cannot exhaust the HTTP budget
# before the fallback chain completes.
FALLBACK_MODELS = [
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-20b:free",
]
# Hard cap per model attempt. With a 120s HTTP client budget this leaves room
# for ~2-3 fallback attempts even if the primary hangs to the cap.
MODEL_TIMEOUT_S = 40

SYSTEM_PROMPT = (
    "You are a Certified Medical Billing & Coding Specialist (AAPC CPC/CCP). "
    "You convert discharge summary clinical data into a standardized insurance "
    "claim justification dossier. Given a diagnosis and medication regimen, "
    "you assign correct primary/secondary ICD-10 diagnostic codes, write a "
    "concise medical-necessity rationale, and produce a billing line-item "
    "breakdown with coverage justification. Be precise, clinically accurate, "
    "and conservative — never fabricate codes; if a code is uncertain, give "
    "the closest clinically defensible match and note the basis in the "
    "rationale.\n\n"
    "STRICT OUTPUT FORMAT: Respond with ONLY a single minified JSON object "
    "that exactly matches the provided schema. Do NOT include any prose, "
    "explanations, headings, or markdown code fences (no ```json blocks). "
    "Output the raw JSON object and nothing else."
)

# Exact JSON shape the model must return. Plain-JSON prompting (not tool
# calling) is used because the free OpenRouter models are inconsistent at
# OpenAI function-calling — the response is parsed + fenced-stripped below.
CLAIM_SCHEMA = (
    "Return EXACTLY this JSON shape (minified, no code fences):\n"
    "{\n"
    '  "icd10_codes": [{"code":"string","description":"string","rank":"primary|secondary"}],\n'
    '  "medical_necessity_brief": ["string","string","string"],\n'
    '  "claim_summary": {\n'
    '    "currency":"INR",\n'
    '    "line_items":[{"description":"string","cpt_or_hcpcs":"string","estimated_cost":"₹0","coverage":"covered|partial|review"}],\n'
    '    "total_estimated_cost":"₹0",\n'
    '    "coverage_justification":"string"\n'
    "  }\n"
    "}\n"
    "`medical_necessity_brief` MUST contain exactly 3 bullet strings. "
    "`icd10_codes` MUST include at least one primary code."
)

# Shared scrubber instance for the clinical context.
_scrubber = PIIScrubber()

# Friendly sender signature used for the patient claim-status email.
FROM_ADDRESS = os.getenv("CLAIM_FROM_EMAIL", "MedGuardian <claims@resend.dev>")


# ---------------------------------------------------------------------------
# Output schema (strict JSON, enforced via tool-calling)
# ---------------------------------------------------------------------------


class ICD10Code(BaseModel):
    code: str = Field(..., description="ICD-10-CM diagnostic code, e.g. I21.4")
    description: str = Field(..., description="Human-readable code description")
    rank: str = Field(
        ..., description="'primary' or 'secondary'"
    )


class ClaimLineItem(BaseModel):
    description: str = Field(..., description="Service / medication / charge line")
    cpt_or_hcpcs: str = Field(
        ..., description="CPT or HCPCS code if applicable, else 'N/A'"
    )
    estimated_cost: str = Field(
        ..., description="Estimated cost in INR, e.g. '₹4,500'"
    )
    coverage: str = Field(
        ..., description="Coverage disposition: 'covered' | 'partial' | 'review'"
    )


class ClaimSummary(BaseModel):
    currency: str = Field("INR", description="Billing currency")
    line_items: List[ClaimLineItem]
    total_estimated_cost: str = Field(
        ..., description="Grand total estimated cost, e.g. '₹18,200'"
    )
    coverage_justification: str = Field(
        ...,
        description=(
            "Concise narrative explaining why the line items are medically "
            "necessary and eligible for coverage under the diagnosis."
        ),
    )


class ClaimDossier(BaseModel):
    icd10_codes: List[ICD10Code]
    medical_necessity_brief: List[str] = Field(
        ...,
        description=(
            "Exactly 3 bullet-string rationales explaining why the prescribed "
            "medications and stay duration were required for this diagnosis."
        ),
    )
    claim_summary: ClaimSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_json_fences(text: str) -> str:
    """Remove ``` / ```json markdown fences and surrounding prose, returning the
    innermost balanced JSON blob. Free OpenRouter models sometimes wrap JSON in
    fences despite the strict prompt, so this normalizes before json.loads().
    """
    if not text:
        return ""
    # Drop any ```json or ``` fence markers, then trim.
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return ""
    return cleaned[start : end + 1]


def _parse_json_response(text: str) -> dict:
    """Tolerantly parse the model's raw text response into a dict.

    Free OpenRouter models frequently wrap the JSON in markdown fences or
    surround it with conversational prose ("Here is the dossier:\\n```json
    {...}```\\nLet me know if..."). We forcibly extract the outermost {...}
    blob with a greedy DOTALL regex — completely ignoring any garbage or
    markdown before/after the JSON — strip stray fences, then ``json.loads``
    with a single→double quote fallback.
    """
    if not text:
        return {}
    # 1. Aggressive greedy extraction of the outermost JSON object, ignoring
    #    any conversational garbage or markdown before/after it.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        blob = match.group(0)
    else:
        # No brace-delimited span — fall back to the fence-stripping path.
        blob = _strip_json_fences(text)
    # Strip any stray ``` / ```json fences the model may have left inside the
    # captured span, then trim.
    blob = re.sub(r"```(?:json)?", "", blob, flags=re.IGNORECASE).strip()
    if not blob:
        return {}
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        try:
            return json.loads(blob.replace("'", '"'))
        except json.JSONDecodeError:
            return {}


def _extract_clinical_context(patient_data: dict) -> dict:
    """Pull the clinically-relevant subset of patient_data and scrub PII.

    The LLM only needs the discharge contract fields to do billing/coding; we
    exclude free-text patient responses and run `PIIScrubber.anonymize_payload`
    on the serialized context so phones, emails, and project identifiers are
    redacted before generation.
    """
    extracted = patient_data.get("extracted") or {}
    safety_flags = patient_data.get("safety_flags") or []

    context = prepare_clinical_payload(
        {
        "diagnosis": extracted.get("diagnosis"),
        "medications": extracted.get("medications", []),
        "precautions": extracted.get("precautions", []),
        "follow_up_date": extracted.get("follow_up_date"),
        "warning_signs": extracted.get("warning_signs", []),
        "safety_flags": safety_flags,
        # Comprehension context only — no patient free-text is forwarded.
        "teach_back_comprehension_score": (
            (patient_data.get("teach_back") or {}).get("understanding_score")
        ),
        },
        names=collect_explicit_names(patient_data),
        scrubber=_scrubber,
    )
    serialized = json.dumps(context, ensure_ascii=False, indent=2)
    return {"_scrubbed_context": serialized}


def _build_user_prompt(patient_data: dict) -> str:
    scrubbed = _extract_clinical_context(patient_data)["_scrubbed_context"]
    return (
        "DISCHARGE CLINICAL DATA (PII redacted):\n"
        f"{scrubbed}\n\n"
        "As a Certified Medical Billing & Coding Specialist, build the insurance "
        "claim justification dossier for this discharge:\n"
        "  1. Assign primary and any secondary ICD-10 diagnostic codes for the "
        "diagnosis.\n"
        "  2. Write a 3-bullet medical-necessity brief explaining why the "
        "prescribed medications and the stay duration were required for this "
        "specific diagnosis.\n"
        "  3. Produce a billing line-item breakdown (medications, procedures, "
        "stay) with CPT/HCPCS where applicable, estimated INR costs, a coverage "
        "disposition per line, and an overall coverage justification.\n\n"
        f"{CLAIM_SCHEMA}\n\n"
        "Respond with ONLY the raw JSON object (no code fences, no prose)."
    )


# ---------------------------------------------------------------------------
# LLM call with robust fallback handling
# ---------------------------------------------------------------------------


async def _call_model(model: str, user_prompt: str):
    """Single OpenRouter completion against the given model.

    Uses plain JSON-in-content prompting (no tool-calling): the free OpenRouter
    models are unreliable at OpenAI function-calling, so we ask for a raw JSON
    object in `message.content` and parse it ourselves.

    The call is wrapped in `asyncio.wait_for(MODEL_TIMEOUT_S)` so a single
    slow/hanging model raises `asyncio.TimeoutError` (caught by the caller's
    fallback loop) instead of consuming the entire HTTP client budget and
    surfacing as an `httpx.ReadTimeout` to the caller before the fallback chain
    can complete.
    """
    coro = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1500,
    )
    return await asyncio.wait_for(coro, timeout=MODEL_TIMEOUT_S)


async def _generate_dossier(patient_data: dict) -> dict:
    """Generate the strict-JSON dossier, falling back across models on error.

    The model returns raw text; we strip any ```json fences, parse to a dict,
    and validate against the `ClaimDossier` schema so the output always
    conforms to the contract (with defaults filled).
    """
    user_prompt = _build_user_prompt(patient_data)

    last_exc: Exception | None = None
    for model in (MODEL, *FALLBACK_MODELS):
        try:
            completion = await _call_model(model, user_prompt)
            content = completion.choices[0].message.content or ""
            parsed = _parse_json_response(content)
            if not parsed:
                raise RuntimeError(
                    f"Model {model} returned no parseable JSON object."
                )
            # Validate + normalize against the strict schema (fills defaults).
            return ClaimDossier.model_validate(parsed).model_dump()
        except Exception as exc:  # noqa: BLE001 — try next model
            last_exc = exc
            print(
                f"[Claim Engine] {model} failed ({type(exc).__name__}: {exc}); "
                "trying fallback."
            )

    # All models failed — return a minimal, well-formed fallback dossier so the
    # endpoint never 500s. Flagged for manual review.
    print(f"[Claim Engine] All models exhausted; returning review-flagged "
          f"fallback dossier. Last error: {last_exc}")
    return _fallback_dossier(patient_data)


def _fallback_dossier(patient_data: dict) -> dict:
    extracted = patient_data.get("extracted") or {}
    diagnosis = extracted.get("diagnosis", "Unspecified")
    meds = extracted.get("medications", [])
    return {
        "icd10_codes": [
            {
                "code": "N/A",
                "description": f"Pending coder review for: {diagnosis}",
                "rank": "primary",
            }
        ],
        "medical_necessity_brief": [
            f"Discharge diagnosis: {diagnosis}.",
            f"Prescribed regimen ({len(meds)} item(s)) requires medical-necessity review.",
            "Claim generated under automated fallback — manual coder review required.",
        ],
        "claim_summary": {
            "currency": "INR",
            "line_items": [
                {
                    "description": "Automated claim — pending manual review",
                    "cpt_or_hcpcs": "N/A",
                    "estimated_cost": "₹0",
                    "coverage": "review",
                }
            ],
            "total_estimated_cost": "₹0",
            "coverage_justification": (
                "Automated generation failed; claim forwarded for manual "
                "billing & coding review before TPA submission."
            ),
        },
        "_fallback": True,
    }


# ---------------------------------------------------------------------------
# HTML formatter (Claim Summary Report)
# ---------------------------------------------------------------------------


def _esc(text: Any) -> str:
    """Minimal HTML escaping for safe rendering."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_claim_html(dossier: dict) -> str:
    """Render the dossier JSON as a clean, frontend-ready Claim Summary Report."""
    icd_rows = "".join(
        f"<tr><td><code>{_esc(c.get('code'))}</code></td>"
        f"<td>{_esc(c.get('description'))}</td>"
        f"<td>{_esc(c.get('rank'))}</td></tr>"
        for c in dossier.get("icd10_codes", [])
    )
    bullets = "".join(
        f"<li>{_esc(b)}</li>" for b in dossier.get("medical_necessity_brief", [])
    )
    summary = dossier.get("claim_summary", {}) or {}
    line_rows = "".join(
        f"<tr><td>{_esc(li.get('description'))}</td>"
        f"<td><code>{_esc(li.get('cpt_or_hcpcs'))}</code></td>"
        f"<td>{_esc(li.get('estimated_cost'))}</td>"
        f"<td>{_esc(li.get('coverage'))}</td></tr>"
        for li in summary.get("line_items", [])
    )
    fallback_banner = ""
    if dossier.get("_fallback"):
        fallback_banner = (
            '<div style="background:#fff3cd;color:#856404;padding:10px;'
            'border-radius:8px;margin-bottom:16px;border:1px solid #ffeeba;">'
            "⚠ Automated generation failed — this dossier is a placeholder "
            "pending manual coder review.</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
         color: #1f2937; background: #f8fafc; margin: 0; padding: 24px; }}
  .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
          padding: 20px; max-width: 820px; margin: 0 auto 20px;
          box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  h1 {{ color: #1d4ed8; font-size: 22px; margin: 0 0 4px; }}
  h2 {{ color: #1e3a8a; font-size: 16px; margin: 20px 0 10px;
       border-bottom: 2px solid #e0e7ff; padding-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid #eef2ff; }}
  th {{ color: #3730a3; font-weight: 600; background: #f1f5ff; }}
  code {{ background: #eef2ff; padding: 2px 6px; border-radius: 4px;
         font-size: 13px; color: #3730a3; }}
  ul {{ margin: 0; padding-left: 20px; }} li {{ margin: 6px 0; line-height: 1.5; }}
  .muted {{ color: #6b7280; font-size: 12px; }}
  .total {{ font-weight: 700; color: #1d4ed8; font-size: 16px; }}
</style>
</head>
<body>
{fallback_banner}
<div class="card">
  <h1>MedGuardian — Claim Summary Report</h1>
  <p class="muted">Auto-Claim &amp; Insurance Justification Engine · TPA pre-submission dossier</p>

  <h2>ICD-10 Diagnostic Codes</h2>
  <table>
    <thead><tr><th>Code</th><th>Description</th><th>Rank</th></tr></thead>
    <tbody>{icd_rows or '<tr><td colspan="3">No codes assigned.</td></tr>'}</tbody>
  </table>

  <h2>Medical Necessity Brief</h2>
  <ul>{bullets or '<li>No rationale provided.</li>'}</ul>
</div>

<div class="card">
  <h2>Billing Line Items &amp; Coverage Justification</h2>
  <table>
    <thead><tr><th>Description</th><th>CPT/HCPCS</th>
    <th>Est. Cost ({_esc(summary.get('currency', 'INR'))})</th><th>Coverage</th></tr></thead>
    <tbody>{line_rows or '<tr><td colspan="4">No line items.</td></tr>'}</tbody>
  </table>
  <p class="total">Total Estimated Cost: {_esc(summary.get('total_estimated_cost'))}</p>
  <h2>Coverage Justification</h2>
  <p style="line-height:1.6;">{_esc(summary.get('coverage_justification'))}</p>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# PDF rendering — server-side Claim Summary Report PDF
# ---------------------------------------------------------------------------

def format_claim_pdf(dossier: dict) -> bytes:
    """Render the dossier JSON as a real, selectable-text PDF (A4, paginated).

    Why server-side and not the frontend's html2pdf / jspdf stack:
      * The dossier is already server-rendered — re-rendering it as text on
        the server avoids a 1.5MB client bundle (medguardian runs on mobile
        for elderly patients) AND keeps the output as REAL selectable text,
        not a rasterized screenshot of styled DOM.
      * pymupdf is already pinned in requirements.txt (1.26.5) — no new
        system dependency, no apt-get weasyprint, no Chromium.

    Output is paginated automatically: long medical-necessity rationales or
    multi-page billing tables flow across A4 pages with running header on
    each page. PyMuPDF's `insert_textbox` does text-wrap; the page-break is
    driven by `remaining_rect` math so we never clip content.

    Falls back to the same `_fallback` banner as the HTML report so the
    operator sees the same warning when the LLM didn't run.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - pymupdf is in requirements
        raise RuntimeError(
            "pymupdf is required for server-side PDF rendering. "
            "Install with `pip install pymupdf`."
        ) from exc

    icd_codes = dossier.get("icd10_codes", []) or []
    bullets = dossier.get("medical_necessity_brief", []) or []
    summary = dossier.get("claim_summary", {}) or {}
    line_items = summary.get("line_items", []) or []
    currency = summary.get("currency", "INR") or "INR"
    total_cost = summary.get("total_estimated_cost", "pending review")
    coverage_justification = summary.get("coverage_justification", "pending review")
    is_fallback = bool(dossier.get("_fallback"))

    # A4 portrait at 72 DPI: 595 x 842 pt. We use a 56-pt margin all round
    # so the content area is 483 x 730 pt. Same margins as the HTML report
    # so the two outputs feel consistent.
    page_w, page_h = 595, 842
    margin = 56
    content_w = page_w - 2 * margin
    content_x = margin
    top_y = margin
    bottom_y = page_h - margin

    # Fonts — PyMuPDF ships the PDF Base14 fonts built in. We use the full
    # Base14 names ("Helvetica", "Helvetica-Bold", "Courier") rather than the
    # legacy abbreviations ("helv", "cour") because PyMuPDF's font lookup
    # only matches the full names on the `insert_text` codepath.
    font_title = "Helvetica-Bold"
    font_h2 = "Helvetica-Bold"
    font_body = "Helvetica"
    font_mono = "Courier"

    # Colour palette mirrors the HTML report (Tailwind indigo/slate scale).
    COLOR_TITLE = (0.114, 0.443, 0.847)   # #1d4ed8
    COLOR_H2 = (0.118, 0.227, 0.541)      # #1e3a8a
    COLOR_MUTED = (0.424, 0.451, 0.502)   # #6b7280
    COLOR_TOTAL = COLOR_TITLE
    COLOR_TABLE_HEADER_BG = (0.945, 0.961, 1.0)  # #f1f5ff
    COLOR_TABLE_BORDER = (0.878, 0.890, 0.969)  # #e0e7ff
    COLOR_CODE_BG = (0.933, 0.945, 1.0)   # #eef2ff

    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)
    cursor_y = top_y

    def _new_page() -> fitz.Page:
        nonlocal page, cursor_y
        page = doc.new_page(width=page_w, height=page_h)
        cursor_y = top_y
        return page

    def _ensure_space(needed: float) -> None:
        """Start a new page if `needed` pt wouldn't fit on the current page."""
        nonlocal cursor_y
        if cursor_y + needed > bottom_y:
            _new_page()

    def _draw_running_header() -> None:
        """Light header on every page so the multi-page PDF stays identifiable."""
        page.insert_text(
            (content_x, top_y - 24),
            "MedGuardian — Claim Summary Report (TPA pre-submission dossier)",
            fontname=font_body,
            fontsize=8,
            color=COLOR_MUTED,
        )

    def _wrap_text(text: str, fontname: str, fontsize: float, max_width: float) -> List[str]:
        """Word-wrap a paragraph into lines that fit `max_width` pt."""
        if not text:
            return [""]
        words = str(text).split()
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = (current + " " + word).strip()
            if fitz.get_text_length(candidate, fontname=fontname, fontsize=fontsize) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def _heading(text: str, color, size: int, fontname: str) -> None:
        nonlocal cursor_y
        _ensure_space(size + 6)
        page.insert_text(
            (content_x, cursor_y + size),
            text,
            fontname=fontname,
            fontsize=size,
            color=color,
        )
        cursor_y += size + 6
        if fontname == font_h2:
            # Underline the h2 the same way the HTML report does (the 2-pt
            # bottom border). PyMuPDF doesn't have native draw-line for the
            # page, so we use draw_rect.
            page.draw_rect(
                fitz.Rect(content_x, cursor_y, content_x + content_w, cursor_y + 1.5),
                color=COLOR_TABLE_BORDER,
                fill=COLOR_TABLE_BORDER,
                width=0,
            )
            cursor_y += 6

    def _paragraph(text: str, color, size: int = 11, fontname: str = font_body, line_height: float = 14) -> None:
        nonlocal cursor_y
        for line in _wrap_text(text, fontname, size, content_w):
            _ensure_space(line_height)
            page.insert_text(
                (content_x, cursor_y + size),
                line,
                fontname=fontname,
                fontsize=size,
                color=color,
            )
            cursor_y += line_height

    def _bullet(text: str) -> None:
        nonlocal cursor_y
        bullet_x = content_x + 6
        text_x = content_x + 22
        # Bullet glyph drawn in line with the first text line.
        for idx, line in enumerate(_wrap_text(text, font_body, 11, content_w - 22)):
            _ensure_space(14)
            if idx == 0:
                page.insert_text((bullet_x, cursor_y + 11), "•", fontname=font_body, fontsize=11, color=COLOR_H2)
            page.insert_text((text_x, cursor_y + 11), line, fontname=font_body, fontsize=11, color=(0.12, 0.16, 0.22))
            cursor_y += 14

    def _table(headers: List[str], rows: List[List[str]], col_widths: List[float], code_columns: set = None) -> None:
        """Render a simple table with header background and bottom borders.

        `col_widths` are absolute pt, summing to <= content_w. `code_columns`
        is a set of 0-indexed column numbers rendered with the mono font
        inside a tinted background (to match the HTML report's <code> pills).
        """
        nonlocal cursor_y
        code_columns = code_columns or set()
        row_h = 18
        header_h = 20

        def _col_x(i: int) -> float:
            return content_x + sum(col_widths[:i])

        def _col_text(i: int) -> str:
            return headers[i] if i < len(headers) else ""

        # Header
        _ensure_space(header_h + 4)
        page.draw_rect(
            fitz.Rect(content_x, cursor_y, content_x + sum(col_widths), cursor_y + header_h),
            color=COLOR_TABLE_HEADER_BG,
            fill=COLOR_TABLE_HEADER_BG,
            width=0,
        )
        for i, w in enumerate(col_widths):
            page.insert_text(
                (_col_x(i) + 8, cursor_y + 13),
                _col_text(i),
                fontname=font_h2,
                fontsize=10,
                color=(0.215, 0.188, 0.639),  # #3730a3
            )
        cursor_y += header_h
        # Underline
        page.draw_rect(
            fitz.Rect(content_x, cursor_y, content_x + sum(col_widths), cursor_y + 1),
            color=COLOR_TABLE_BORDER,
            fill=COLOR_TABLE_BORDER,
            width=0,
        )
        cursor_y += 2

        # Rows
        for row in rows:
            # Split any long cell across multiple visual lines so wide cells
            # don't clip past the column.
            wrapped_cells: List[List[str]] = []
            for i, cell in enumerate(row):
                fontname = font_mono if i in code_columns else font_body
                wrapped_cells.append(
                    _wrap_text(str(cell or ""), fontname, 10, col_widths[i] - 12)
                )
            row_line_count = max(len(c) for c in wrapped_cells) if wrapped_cells else 1
            row_total_h = row_line_count * row_h + 4
            _ensure_space(row_total_h)

            for i, cell_lines in enumerate(wrapped_cells):
                x = _col_x(i) + 8
                if i in code_columns:
                    # Tinted pill behind the mono text — same look as <code>.
                    bg_w = min(
                        col_widths[i] - 4,
                        max(20.0, fitz.get_text_length(" ".join(cell_lines), fontname=font_mono, fontsize=10) + 10),
                    )
                    page.draw_rect(
                        fitz.Rect(_col_x(i) + 2, cursor_y + 2, _col_x(i) + 2 + bg_w, cursor_y + 12),
                        color=COLOR_CODE_BG,
                        fill=COLOR_CODE_BG,
                        width=0,
                    )
                    page.insert_text(
                        (x, cursor_y + 11),
                        cell_lines[0] if cell_lines else "",
                        fontname=font_mono,
                        fontsize=10,
                        color=(0.215, 0.188, 0.639),
                    )
                else:
                    for j, line in enumerate(cell_lines):
                        page.insert_text(
                            (x, cursor_y + 11 + j * row_h),
                            line,
                            fontname=font_body,
                            fontsize=10,
                            color=(0.12, 0.16, 0.22),
                        )
            cursor_y += row_total_h
            # Row separator
            page.draw_rect(
                fitz.Rect(content_x, cursor_y, content_x + sum(col_widths), cursor_y + 0.5),
                color=COLOR_TABLE_BORDER,
                fill=COLOR_TABLE_BORDER,
                width=0,
            )
        cursor_y += 8

    # First-page header
    _draw_running_header()
    cursor_y = top_y  # reset because _draw_running_header used top_y for offset math

    # Fallback banner — identical wording to the HTML report.
    if is_fallback:
        _ensure_space(40)
        page.draw_rect(
            fitz.Rect(content_x, cursor_y, content_x + content_w, cursor_y + 40),
            color=(1.0, 0.953, 0.804),  # #fff3cd
            fill=(1.0, 0.953, 0.804),
            width=0,
        )
        _paragraph(
            "⚠ Automated generation failed — this dossier is a placeholder "
            "pending manual coder review.",
            color=(0.522, 0.392, 0.016),
            size=10,
        )
        cursor_y += 8

    # Title block
    _heading("MedGuardian — Claim Summary Report", COLOR_TITLE, 22, font_title)
    _paragraph(
        "Auto-Claim & Insurance Justification Engine · TPA pre-submission dossier",
        color=COLOR_MUTED,
        size=9,
    )
    cursor_y += 8

    # ICD-10 codes table
    _heading("ICD-10 Diagnostic Codes", COLOR_H2, 14, font_h2)
    icd_table_rows = [
        [c.get("code", ""), c.get("description", ""), c.get("rank", "")]
        for c in icd_codes
    ] or [["No codes assigned.", "", ""]]
    # Column widths sum to content_w (483).
    _table(
        headers=["Code", "Description", "Rank"],
        rows=icd_table_rows,
        col_widths=[70, 333, 80],
        code_columns={0},
    )

    # Medical necessity brief
    _heading("Medical Necessity Brief", COLOR_H2, 14, font_h2)
    if bullets:
        for b in bullets:
            _bullet(b)
    else:
        _bullet("No rationale provided.")
    cursor_y += 6

    # Billing line items
    _heading("Billing Line Items & Coverage Justification", COLOR_H2, 14, font_h2)
    line_table_rows = [
        [
            li.get("description", ""),
            li.get("cpt_or_hcpcs", ""),
            li.get("estimated_cost", ""),
            li.get("coverage", ""),
        ]
        for li in line_items
    ] or [["No line items.", "", "", ""]]
    _table(
        headers=["Description", "CPT/HCPCS", f"Est. Cost ({currency})", "Coverage"],
        rows=line_table_rows,
        col_widths=[200, 70, 75, 138],
        code_columns={1},
    )

    # Total + coverage justification (paragraphs, not table).
    _ensure_space(20)
    _paragraph(
        f"Total Estimated Cost: {total_cost}",
        color=COLOR_TOTAL,
        size=13,
        fontname=font_h2,
        line_height=16,
    )
    cursor_y += 4
    _heading("Coverage Justification", COLOR_H2, 14, font_h2)
    _paragraph(coverage_justification or "pending review", color=(0.12, 0.16, 0.22), size=11, line_height=15)

    # Add the running header to every subsequent page too (PyMuPDF doesn't
    # repeat text automatically across pages — we drew page 1's header above
    # and must redraw for any page that auto-flowed after a long table).
    for p in range(1, doc.page_count):
        # Each additional page also gets the running header at the top.
        p.insert_text(
            (content_x, top_y - 24),
            "MedGuardian — Claim Summary Report (TPA pre-submission dossier)",
            fontname=font_body,
            fontsize=8,
            color=COLOR_MUTED,
        )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Patient notification (Resend, graceful fallback)
# ---------------------------------------------------------------------------


def _status_email_body(dossier: dict) -> str:
    """Plain-text claim status note for the patient."""
    summary = dossier.get("claim_summary", {}) or {}
    codes = ", ".join(
        c.get("code", "") for c in dossier.get("icd10_codes", [])
    ) or "pending review"
    return (
        "Hello,\n\n"
        "MedGuardian has generated your insurance claim justification dossier.\n\n"
        f"ICD-10 codes: {codes}\n"
        f"Total estimated cost: {summary.get('total_estimated_cost', 'pending')}\n"
        f"Coverage status: {summary.get('coverage_justification', 'pending review')[:200]}\n\n"
        "This dossier has been forwarded to your TPA for pre-authorization. "
        "You are not required to take any action at this time.\n\n"
        "— MedGuardian Claims Team"
    )


def _send_via_resend(to_email: str, subject: str, body: str) -> None:
    params = {
        "from": FROM_ADDRESS,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    resend.Emails.send(params)


async def _notify_patient(patient_email: str, dossier: dict) -> dict:
    """Email a transparent claim-status copy to the patient.

    Falls back to a terminal print if Resend is unavailable so the demo never
    breaks. Returns a small status dict.
    """
    if not patient_email:
        return {"ok": False, "detail": "no patient_email supplied"}

    if not os.getenv("RESEND_API_KEY"):
        print(
            "\n[Claim Engine] Resend unavailable — printing patient claim-status "
            "copy to terminal."
        )
        print(f"TO PATIENT: {patient_email}")
        print(f"SUBJECT   : Your MedGuardian claim status")
        print("BODY:")
        print(_status_email_body(dossier))
        return {"ok": False, "detail": "RESEND_API_KEY not set; printed to terminal"}

    try:
        await asyncio.to_thread(
            _send_via_resend,
            patient_email,
            "Your MedGuardian claim status",
            _status_email_body(dossier),
        )
        return {"ok": True, "detail": "patient notified via Resend"}
    except Exception as exc:  # noqa: BLE001 — any Resend failure is recoverable
        print(
            f"[Claim Engine] Resend send failed ({type(exc).__name__}: {exc}); "
            "printing patient claim-status copy to terminal."
        )
        print(f"TO PATIENT: {patient_email}")
        print(f"SUBJECT   : Your MedGuardian claim status")
        print("BODY:")
        print(_status_email_body(dossier))
        return {"ok": False, "detail": f"Resend failed: {type(exc).__name__}"}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def generate_claim_dossier(patient_data: dict, patient_email: str) -> dict:
    """Generate the insurance claim justification dossier for a discharge.

    Args:
        patient_data: The shared MedGuardian state object (context.md),
            including `extracted` (diagnosis, medications) and `safety_flags`.
        patient_email: Recipient for the transparent claim-status copy.

    Returns:
        A dict containing the strict-JSON dossier, the rendered HTML Claim
        Summary Report, and the patient-notification status.
    """
    # 1. Generate the strict-JSON dossier (clinical context is scrubbed inside).
    dossier = await _generate_dossier(patient_data)

    # 2. Render the frontend-ready HTML report.
    html_report = format_claim_html(dossier)

    # 3. Email a transparent claim-status copy to the patient.
    notify_status = await _notify_patient(patient_email, dossier)

    return {
        "dossier": dossier,
        "html_report": html_report,
        "patient_notification": notify_status,
    }
