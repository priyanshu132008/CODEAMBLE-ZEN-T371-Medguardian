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

# ---------------------------------------------------------------------------
# OpenRouter client (separate, dedicated instance for this engine)
# ---------------------------------------------------------------------------

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

# Primary model: a reliable free JSON-producing model via OpenRouter. The
# free tiers are inconsistent at OpenAI function-calling, so we use plain
# JSON-in-content prompting and parse the output ourselves (see below).
# These slugs were verified live against OpenRouter (2026-08-08) — the older
# `:free` Llama/Gemini-1.5 slugs have been retired and now 404.
MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
# Fallback models tried in order if the primary is unavailable / rate-limited
# / returns unparseable output. Each is a valid OpenRouter model id verified
# to emit a parseable coded dossier for the bronchitis test case.
FALLBACK_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openai/gpt-oss-20b:free",
    "google/gemma-4-26b-a4b-it:free",
]

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

    context = {
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
    }
    serialized = json.dumps(context, ensure_ascii=False, indent=2)
    # Pass the patient's name to anonymize_payload (regex can't catch arbitrary
    # names) so it is redacted whole-word alongside phones/emails/IDs — one
    # canonical redaction path, consistent with the rest of the API.
    name = patient_data.get("patient_name") or patient_data.get("name")
    names = [name] if name else None
    return {"_scrubbed_context": _scrubber.anonymize_payload(serialized, names=names)}


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
    """
    return await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1500,
    )


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