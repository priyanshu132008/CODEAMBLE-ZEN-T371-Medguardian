"""MedGuardian backend — FastAPI orchestrator.

Orchestrates Agent 1, Agent 2 (Safety Check), and Agent 3 (Teach-Back via Text/Voice).
"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional, Tuple

from dotenv import load_dotenv

# Load environment variables from backend/.env BEFORE importing agents
load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.safety_check import (
    Medication,
    SafetyFlag,
    run_safety_check,
)
from agents.teach_back import evaluate_teach_back
from agents.voice_utils import generate_tts, transcribe_stt, SarvamUnavailableError
from agents.document_intelligence import extract_discharge
from agents.privacy_sandbox import PIIScrubber
from agents.coordinator_engine import dispatch_care_coordination
from agents.claim_engine import generate_claim_dossier
from app.api.routers.auth import router as auth_router
from app.api.routers.patients import router as patients_router

app = FastAPI(title="MedGuardian API", version="0.1.0")
app.include_router(auth_router)
app.include_router(patients_router)

# Privacy Sandbox — every patient-facing free-text input is scrubbed through
# this PII scrubber before it reaches any external cloud LLM. Shared instance
# so the in-memory redaction map persists across requests for the demo.
_pii_scrubber = PIIScrubber()

# Keys whose string values are treated as patient names to explicitly redact
# (the regex scrubber cannot catch arbitrary names, so callers collect any
# known names from the request context and pass them to anonymize_payload).
_NAME_KEYS = {"patient_name", "name", "full_name", "patient"}


def _collect_names(*payloads) -> List[str]:
    """Recursively collect candidate patient names from arbitrary payloads.

    Walks dicts/lists looking for name-like keys ("patient_name", "name",
    "full_name", "patient") with non-empty string values. Used to feed the
    Privacy Sandbox's explicit name-redaction across all LLM-bound endpoints.
    """
    names: List[str] = []

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in _NAME_KEYS and isinstance(v, str) and v.strip():
                    names.append(v.strip())
                elif isinstance(v, (dict, list)):
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    for p in payloads:
        _walk(p)
    return names

# Allow all origins for seamless presentation/local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models (strict JSON contract)
# ---------------------------------------------------------------------------


class SafetyCheckRequest(BaseModel):
    medications: List[Medication]


class SafetyCheckResponse(BaseModel):
    safety_flags: List[SafetyFlag]


class TTSRequest(BaseModel):
    text: str
    language: str


class TeachBackRequest(BaseModel):
    extracted: dict
    current_teach_back: dict
    patient_response: str
    # Optional session context for the Agent 4 auto-trigger. When omitted,
    # fallback demo emails are used so the coordinator still fires for demos.
    safety_flags: List[dict] = []
    patient_email: Optional[str] = None
    doctor_email: Optional[str] = None
    language: str = "English"


class EscalateSimulateRequest(BaseModel):
    symptom: str


class CoordinatorTriggerRequest(BaseModel):
    patient_data: dict
    patient_email: str
    doctor_email: str
    language: str = "English"


class ClaimGenerateRequest(BaseModel):
    patient_data: dict
    patient_email: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/safety-check", response_model=SafetyCheckResponse)
def safety_check(request: SafetyCheckRequest) -> SafetyCheckResponse:
    """Run the rule-based safety cross-check on the supplied medications."""
    flags = run_safety_check(request.medications)
    return SafetyCheckResponse(safety_flags=flags)


# ---------------------------------------------------------------------------
# Document Upload / OCR Intake (Agent 1 & 2 — vision extraction + safety check)
# ---------------------------------------------------------------------------

UPLOAD_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}


def _run_safety_check_from_extracted(extracted: dict) -> List[dict]:
    """Run Agent 2 (rule-based safety check) over the medications extracted by
    Agent 1, returning the flags as plain dicts so they slot directly into the
    shared JSON contract's `safety_flags` array. Tolerates malformed med rows
    from OCR by skipping anything that won't validate.
    """
    medications: List[Medication] = []
    for m in extracted.get("medications", []) or []:
        try:
            medications.append(Medication(**m))
        except Exception:  # noqa: BLE001 — skip a badly-shaped OCR row
            continue
    flags = run_safety_check(medications)
    return [f.model_dump() for f in flags]


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """Agent 1: accept a photo/scan of a discharge summary, run vision OCR, and
    return the structured discharge data as the shared JSON contract state
    object (context.md). The frontend drives the whole pipeline from this.
    """
    import uuid

    if file.content_type not in UPLOAD_ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported file type. Please upload a JPG or PNG photo of the "
                "discharge summary for OCR extraction."
            ),
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload.")

    try:
        extracted = await extract_discharge(file_bytes, file.content_type)
    except Exception as exc:  # noqa: BLE001 — surface a clear upstream error
        raise HTTPException(
            status_code=502,
            detail=f"OCR extraction failed: {exc}",
        ) from exc

    # Agent 2: run the rule-based safety cross-check on the extracted
    # medications so the upload output is a complete Agent 1 & 2 contract —
    # the exact shape required as input by /api/teach-back, /api/coordinator/
    # trigger, and /api/claim/generate.
    safety_flags = _run_safety_check_from_extracted(extracted)

    return {
        "patient_id": str(uuid.uuid4()),
        "extracted": extracted,
        "safety_flags": safety_flags,
        "teach_back": {
            "questions_asked": [],
            "patient_responses": [],
            "understanding_score": 0,
            "corrections_given": [],
        },
        "language": "en",
    }


# ---------------------------------------------------------------------------
# Teach-Back Text Endpoint (Agent 3 — LLM evaluation via OpenRouter)
# ---------------------------------------------------------------------------

# Agent 4 auto-trigger thresholds. A teach-back session is "complete"
# (handoff-worthy) when the patient demonstrates adequate comprehension OR
# the Q&A has reached a minimum depth (so the coordinator still fires for
# low-literacy patients who struggle to reach the passing threshold).
COMPREHENSION_PASS_THRESHOLD = 70
TEACH_BACK_MIN_QUESTIONS_FOR_HANDOFF = 3

# Demo fallback recipients used when the session does not supply real emails.
# Defaults to the verified Resend sandbox delivery address so Agent 4's
# auto-triggered emails actually deliver during the live demo (the sandbox
# sender only delivers to the account owner's verified inbox).
DEMO_PATIENT_EMAIL = os.getenv("DEMO_PATIENT_EMAIL", "priyanshucreator3@gmail.com")
DEMO_DOCTOR_EMAIL = os.getenv("DEMO_DOCTOR_EMAIL", "priyanshucreator3@gmail.com")


def _teach_back_is_complete(updated_state: dict) -> Tuple[bool, str]:
    """Return (is_complete, reason) for the teach-back session."""
    score = int(updated_state.get("understanding_score", 0) or 0)
    questions_asked = updated_state.get("questions_asked", []) or []
    if score >= COMPREHENSION_PASS_THRESHOLD:
        return True, f"comprehension_score={score} >= {COMPREHENSION_PASS_THRESHOLD}"
    if len(questions_asked) >= TEACH_BACK_MIN_QUESTIONS_FOR_HANDOFF:
        return True, (
            f"questions_asked={len(questions_asked)} >= "
            f"{TEACH_BACK_MIN_QUESTIONS_FOR_HANDOFF}"
        )
    return False, f"score={score}, questions={len(questions_asked)} — not yet complete"


async def _run_coordinator_in_background(
    patient_data: dict, patient_email: str, doctor_email: str, language: str
) -> None:
    """Background coroutine: generate + dispatch Agent 4 emails without blocking
    the teach-back API response. All failures are logged, never raised, so a
    coordinator outage can never break the teach-back flow.
    """
    try:
        # Bold target log so we can visually confirm the correct verified
        # delivery address in the terminal during the live demo.
        print(f"\033[1m[Agent 4] Attempting to send emails to {patient_email} and {doctor_email}\033[0m")
        print(
            f"[Coordinator] Background trigger fired → doctor={doctor_email}, "
            f"patient={patient_email}, language={language}"
        )
        result = await dispatch_care_coordination(
            patient_data=patient_data,
            patient_email=patient_email,
            doctor_email=doctor_email,
            language=language,
        )
        print(
            f"[Coordinator] Background complete: status={result['status']} | "
            f"{result['detail']}"
        )
    except Exception as exc:  # noqa: BLE001 — must not escape the task
        print(f"[Coordinator] Background trigger FAILED: {type(exc).__name__}: {exc}")


@app.post("/api/teach-back")
async def teach_back(request: TeachBackRequest) -> dict:
    """Evaluate a patient's teach-back text response and return the updated state.

    On completion, Agent 4 (Care Coordinator) is triggered in the background via
    `asyncio.create_task` so the clinical handoff + patient pulse-check emails
    are generated without blocking this response to the UI.
    """
    # Privacy Sandbox — scrub PII from the patient's free-text response before
    # it is sent to the external teach-back LLM. Collect any known patient
    # name from the request context so it is explicitly redacted (regex can't
    # catch arbitrary names).
    names = _collect_names(request.extracted, request.current_teach_back)
    scrubbed_response = _pii_scrubber.anonymize_payload(
        request.patient_response, names=names
    )
    print(f"[Privacy Sandbox] Scrubbed Payload (teach-back): {scrubbed_response}")
    updated_state = await evaluate_teach_back(
        extracted_data=request.extracted,
        current_teach_back_state=request.current_teach_back,
        new_patient_response=scrubbed_response,
    )

    # Agent 4 auto-trigger — fire only once the teach-back session is complete.
    is_complete, reason = _teach_back_is_complete(updated_state)
    if is_complete:
        teach_back_score = int(updated_state.get("understanding_score", 0) or 0)
        # Assemble the shared state object (context.md) for the coordinator.
        patient_data = {
            "extracted": request.extracted,
            "safety_flags": request.safety_flags,
            "teach_back": updated_state,
            "language": request.language,
        }
        patient_email = request.patient_email or DEMO_PATIENT_EMAIL
        doctor_email = request.doctor_email or DEMO_DOCTOR_EMAIL
        print(
            f"[Coordinator] Teach-Back complete ({reason}); scheduling Agent 4 "
            f"background trigger (score={teach_back_score})."
        )
        asyncio.create_task(
            _run_coordinator_in_background(
                patient_data=patient_data,
                patient_email=patient_email,
                doctor_email=doctor_email,
                language=request.language,
            )
        )
    else:
        print(
            f"[Coordinator] Teach-Back not yet complete ({reason}); "
            f"Agent 4 not triggered."
        )

    return updated_state


# ---------------------------------------------------------------------------
# Unified Voice Interface Subroute (Agent 3 Voice Array Integration)
# ---------------------------------------------------------------------------


@app.post("/api/voice/chat")
async def voice_chat(
    file: UploadFile = File(...),
    extracted_json: str = Form(...),
    current_state_json: str = Form(...)
) -> dict:
    """
    Unified voice handler for the presentation dashboard.
    
    1. Transcribes incoming audio streaming fragments via Sarvam AI STT.
    2. Seamlessly evaluates the transcription through the Agent 3 Teach-Back pipeline.
    3. Auto-synthesizes response audio via Sarvam AI TTS for total conversational loop logic.
    """
    import json
    
    # Step 1: Process STT
    audio_bytes = await file.read()
    patient_text = await transcribe_stt(audio_bytes)

    # Parse incoming form payloads
    extracted_data = json.loads(extracted_json)
    current_state = json.loads(current_state_json)

    # Privacy Sandbox — scrub PII from the transcription before it reaches the
    # external teach-back LLM. Collect any known patient name from the session
    # context so it is explicitly redacted alongside regex PII.
    names = _collect_names(extracted_data, current_state)
    scrubbed_text = _pii_scrubber.anonymize_payload(patient_text, names=names)
    print(f"[Privacy Sandbox] Scrubbed Payload (voice/chat): {scrubbed_text}")

    # Step 2: Route directly through Agent 3 Core (with the scrubbed transcript)
    updated_state = await evaluate_teach_back(
        extracted_data=extracted_data,
        current_teach_back_state=current_state,
        new_patient_response=scrubbed_text,
    )

    # Step 3: Automatically generate TTS audio for the agent's new question feedback
    # Extracts the latest question string or falls back cleanly
    latest_question = updated_state.get("questions_asked", ["Thank you for completing the verification."])[-1]
    audio_base64 = await generate_tts(latest_question, "en-IN")

    return {
        "status": "success",
        "transcription": scrubbed_text,
        "updated_state": updated_state,
        "audio_base64": audio_base64
    }


# ---------------------------------------------------------------------------
# Raw / Atomic Voice Endpoints (Sarvam AI: TTS + STT)
# ---------------------------------------------------------------------------


@app.post("/api/voice/tts")
async def voice_tts(request: TTSRequest) -> dict:
    """Convert text to speech; returns a base64-encoded audio string."""
    audio_base64 = await generate_tts(request.text, request.language)
    return {"audio_base64": audio_base64}


@app.post("/api/voice/stt")
async def voice_stt(file: UploadFile) -> dict:
    """Transcribe an uploaded audio file; returns the transcript text.

    Returns a 503 with a clean JSON message when the Sarvam STT provider is
    down so the frontend can gracefully fall back to typed input.
    """
    audio_bytes = await file.read()
    try:
        transcript = await transcribe_stt(audio_bytes)
    except SarvamUnavailableError as exc:
        # Sarvam is down (503/timeout/etc.) — return a clean JSON message so
        # the frontend can prompt the user to type instead of breaking.
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.user_message},
        )
    # Privacy Sandbox — scrub PII from the transcript before it is returned /
    # forwarded to any downstream cloud processing.
    scrubbed_transcript = _pii_scrubber.anonymize_payload(transcript)
    print(f"[Privacy Sandbox] Scrubbed Payload (voice/stt): {scrubbed_transcript}")
    return {"text": scrubbed_transcript}


# ---------------------------------------------------------------------------
# Mock endpoints (Agents 4 & 5 — simulated for Phase 1)
# ---------------------------------------------------------------------------


@app.get("/api/reminders/simulate")
def reminders_simulate() -> dict:
    """Static mock WhatsApp reminder thread for Agent 4 (Adherence)."""
    return {
        "thread": [
            {
                "role": "system",
                "message": (
                    "WhatsApp Reminder: It is time to take your Omeprazole 40mg. "
                    "Reply 'Done' when you have taken it."
                ),
            },
            {"role": "patient", "message": "Done"},
            {
                "role": "system",
                "message": "Great. Your next medication is Clopidogrel 75mg at 8:00 PM.",
            },
        ]
    }


@app.post("/api/escalate/simulate")
def escalate_simulate(request: EscalateSimulateRequest) -> dict:
    """Static mock symptom escalation for Agent 5."""
    symptom = request.symptom.lower()
    if "chest" in symptom or "pain" in symptom:
        return {
            "escalation_level": "high",
            "message": (
                "You mentioned chest pain, which is on your doctor's Warning "
                "Signs list. Please escalate this immediately and go to the "
                "nearest hospital."
            ),
        }
    return {
        "escalation_level": "low",
        "message": (
            "This symptom is not on your critical warning list, but please "
            "monitor it. Drink water and rest. If it worsens, contact your clinic."
        ),
    }


# ---------------------------------------------------------------------------
# Agent 4 — Automated Care Coordinator (dual-target email engine)
# ---------------------------------------------------------------------------


@app.post("/api/coordinator/trigger")
async def coordinator_trigger(request: CoordinatorTriggerRequest) -> dict:
    """Agent 4: generate and dispatch the dual-target care coordination emails.

    Produces a technical clinical handoff to the doctor and a localized daily
    pulse-check to the patient. The doctor-handoff context is scrubbed through
    the Privacy Sandbox before LLM generation. If Resend is unavailable, both
    generated bodies are printed to the terminal and surfaced in the response.
    """
    result = await dispatch_care_coordination(
        patient_data=request.patient_data,
        patient_email=request.patient_email,
        doctor_email=request.doctor_email,
        language=request.language,
    )
    return result


# ---------------------------------------------------------------------------
# Auto-Claim & Insurance Justification Engine
# ---------------------------------------------------------------------------


@app.post("/api/claim/generate")
async def claim_generate(request: ClaimGenerateRequest) -> dict:
    """Generate the insurance claim justification dossier for a discharge.

    Runs the clinical context through the Privacy Sandbox, then a Certified
    Medical Billing & Coding Specialist persona (OpenRouter: Claude 3.5
    Sonnet, fallback Gemini 1.5 Pro) produces a strict-JSON dossier. Returns
    the JSON dossier plus a rendered HTML Claim Summary Report so the hospital
    UI can render it immediately, and emails a transparent claim-status copy
    to the patient.
    """
    result = await generate_claim_dossier(
        patient_data=request.patient_data,
        patient_email=request.patient_email,
    )
    return result
