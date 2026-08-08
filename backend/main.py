"""MedGuardian backend — FastAPI orchestrator.

Orchestrates Agent 1, Agent 2 (Safety Check), and Agent 3 (Teach-Back via Text/Voice).
"""

from __future__ import annotations

import os
from typing import List

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

app = FastAPI(title="MedGuardian API", version="0.1.0")

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


class EscalateSimulateRequest(BaseModel):
    symptom: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/safety-check", response_model=SafetyCheckResponse)
def safety_check(request: SafetyCheckRequest) -> SafetyCheckResponse:
    """Run the rule-based safety cross-check on the supplied medications."""
    flags = run_safety_check(request.medications)
    return SafetyCheckResponse(safety_flags=flags)


# ---------------------------------------------------------------------------
# Document Upload / OCR Intake (Agent 1 — vision extraction via OpenRouter)
# ---------------------------------------------------------------------------

UPLOAD_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}


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

    return {
        "patient_id": str(uuid.uuid4()),
        "extracted": extracted,
        "safety_flags": [],
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


@app.post("/api/teach-back")
async def teach_back(request: TeachBackRequest) -> dict:
    """Evaluate a patient's teach-back text response and return the updated state."""
    updated_state = await evaluate_teach_back(
        extracted_data=request.extracted,
        current_teach_back_state=request.current_teach_back,
        new_patient_response=request.patient_response,
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
    
    # Step 2: Route directly through Agent 3 Core
    updated_state = await evaluate_teach_back(
        extracted_data=extracted_data,
        current_teach_back_state=current_state,
        new_patient_response=patient_text,
    )
    
    # Step 3: Automatically generate TTS audio for the agent's new question feedback
    # Extracts the latest question string or falls back cleanly
    latest_question = updated_state.get("questions_asked", ["Thank you for completing the verification."])[-1]
    audio_base64 = await generate_tts(latest_question, "en-IN")
    
    return {
        "status": "success",
        "transcription": patient_text,
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
    return {"text": transcript}


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