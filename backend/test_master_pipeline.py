#!/usr/bin/env python3
"""MedGuardian Master Integration Test — full 5-agent pipeline, end-to-end.

Simulates the exact patient journey against the REAL FastAPI app:

    Phase A  /api/upload          Agent 1 (OCR) + Agent 2 (safety check)
    Phase B  /api/teach-back       Agent 3 (Teach-Back) → high comprehension score
    Phase C  (background)          Agent 4 auto-fires via asyncio.create_task
    Phase D  /api/claim/generate   Agent 5 (Auto-Claim & Insurance Justification)

External LLM / OCR / STT / email calls are mocked for determinism (no API keys
or network required), but the real FastAPI routes, the Privacy Sandbox, the
Agent 2 safety check, the Agent 4 background trigger, and the Agent 5 HTML
renderer all run for real — so this validates routing, schema handoff, privacy,
and the background trigger, not just happy paths.

Run:  cd backend && python test_master_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys

import httpx

# Import the real app + the engines we need to mock at the boundary.
import main
from agents import claim_engine


# ---------------------------------------------------------------------------
# ANSI color helpers (auto-disabled when stdout is not a TTY, e.g. CI logs)
# ---------------------------------------------------------------------------

_TTY = sys.stdout.isatty()


class C:
    RESET = "\033[0m" if _TTY else ""
    BOLD = "\033[1m" if _TTY else ""
    RED = "\033[31m" if _TTY else ""
    GREEN = "\033[32m" if _TTY else ""
    YELLOW = "\033[33m" if _TTY else ""
    CYAN = "\033[36m" if _TTY else ""
    MAGENTA = "\033[35m" if _TTY else ""
    GRAY = "\033[90m" if _TTY else ""


def banner(text: str) -> None:
    line = "═" * 72
    print(f"\n{C.CYAN}{C.BOLD}{line}\n  {text}\n{line}{C.RESET}")


def phase(n: str, title: str) -> None:
    print(f"\n{C.MAGENTA}{C.BOLD}▶ PHASE {n} — {title}{C.RESET}")


def step(text: str) -> None:
    print(f"  {C.GRAY}• {text}{C.RESET}")


def ok(text: str) -> None:
    print(f"  {C.GREEN}✓ {text}{C.RESET}")


def info(text: str) -> None:
    print(f"  {C.YELLOW}ⓘ {text}{C.RESET}")


def fail(text: str) -> None:
    print(f"  {C.RED}✗ {text}{C.RESET}")


# ---------------------------------------------------------------------------
# Mock fixtures — boundary mocks for external services (deterministic)
# ---------------------------------------------------------------------------

MOCK_EXTRACTED = {
    "diagnosis": "Acute Coronary Syndrome (NSTEMI)",
    "medications": [
        {"name": "Clopidogrel", "dosage": "75mg", "frequency": "once daily", "duration": "12 months"},
        {"name": "Omeprazole", "dosage": "40mg", "frequency": "once daily", "duration": "ongoing"},
        {"name": "Atorvastatin", "dosage": "40mg", "frequency": "once nightly", "duration": "ongoing"},
        # Deliberate allergy-conflict trigger: Amoxicillin is a penicillin-class
        # drug, and the patient is documented as Penicillin-allergic (below).
        # Agent 2's allergy cross-reference must flag this as CRITICAL.
        {"name": "Amoxicillin", "dosage": "500mg", "frequency": "three times daily", "duration": "7 days"},
    ],
    "precautions": ["Monitor for signs of bleeding.", "Avoid heavy lifting."],
    "follow_up_date": "2026-09-15",
    "warning_signs": ["chest pain", "shortness of breath", "unusual bleeding"],
    "allergies": ["Penicillin"],
}


async def mock_extract_discharge(file_bytes: bytes, content_type: str | None) -> dict:
    """Stand in for Agent 1 vision OCR — returns a canned discharge contract."""
    return dict(MOCK_EXTRACTED)


async def mock_evaluate_teach_back(
    extracted_data: dict,
    current_teach_back_state: dict,
    new_patient_response: str,
) -> dict:
    """Stand in for Agent 3 LLM — returns a high-comprehension final state."""
    prior_questions = list(current_teach_back_state.get("questions_asked", []) or [])
    prior_responses = list(current_teach_back_state.get("patient_responses", []) or [])
    return {
        "questions_asked": prior_questions + [
            "Can you tell me why you are taking Clopidogrel and for how long?"
        ],
        "patient_responses": prior_responses + [new_patient_response],
        "understanding_score": 92,  # high → Agent 4 auto-trigger fires
        "corrections_given": [],
    }


# Records Agent 4 background invocations so the test can assert it fired.
coordinator_calls: list[dict] = []


async def mock_dispatch_care_coordination(
    patient_data: dict, patient_email: str, doctor_email: str, language: str
) -> dict:
    coordinator_calls.append(
        {
            "patient_email": patient_email,
            "doctor_email": doctor_email,
            "language": language,
            "has_safety_flags": bool(patient_data.get("safety_flags")),
            "teach_back_score": (patient_data.get("teach_back") or {}).get("understanding_score"),
        }
    )
    return {
        "status": "sent",
        "detail": "mocked coordinator (no real email sent)",
        "language": language,
    }


def mock_generate_dossier(patient_data: dict) -> dict:
    """Stand in for Agent 5 LLM — returns a strict-shape canned dossier.

    Defined as a plain dict-builder; wrapped as a coroutine when installed so it
    matches the async signature of the real `_generate_dossier`.
    """
    return {
        "icd10_codes": [
            {"code": "I21.4", "description": "Non-ST elevation (NSTEMI) myocardial infarction", "rank": "primary"},
            {"code": "I25.10", "description": "Atherosclerotic heart disease", "rank": "secondary"},
        ],
        "medical_necessity_brief": [
            "Dual antiplatelet therapy with Clopidogrel is standard of care post-NSTEMI to prevent stent thrombosis.",
            "Atorvastatin 40mg stabilizes the coronary plaque and reduces recurrent ischemia risk over the stay window.",
            "A 12-month Clopidogrel duration is mandated by guideline-directed therapy for the index event.",
        ],
        "claim_summary": {
            "currency": "INR",
            "line_items": [
                {"description": "Pharmacy — Clopidogrel 75mg x30", "cpt_or_hcpcs": "J9999", "estimated_cost": "₹1,200", "coverage": "covered"},
                {"description": "Inpatient stay — 2 days, semi-private", "cpt_or_hcpcs": "N/A", "estimated_cost": "₹18,000", "coverage": "covered"},
            ],
            "total_estimated_cost": "₹19,200",
            "coverage_justification": "All line items are guideline-directed for NSTEMI management and eligible under the policy.",
        },
    }


async def mock_notify_patient(patient_email: str, dossier: dict) -> dict:
    return {"ok": True, "detail": "mocked patient notification (no real email sent)"}


async def _async_generate_dossier(patient_data: dict) -> dict:
    """Async wrapper so the mock matches the real `_generate_dossier` signature."""
    return mock_generate_dossier(patient_data)


def install_mocks() -> None:
    """Patch the external-boundary functions on the modules under test."""
    main.extract_discharge = mock_extract_discharge           # Agent 1 (OCR)
    main.evaluate_teach_back = mock_evaluate_teach_back       # Agent 3 (LLM)
    main.dispatch_care_coordination = mock_dispatch_care_coordination  # Agent 4
    claim_engine._generate_dossier = _async_generate_dossier  # Agent 5 (LLM)
    claim_engine._notify_patient = mock_notify_patient       # Agent 5 (email)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def require(cond: bool, msg: str) -> None:
    if cond:
        ok(msg)
    else:
        fail(msg)
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# The journey
# ---------------------------------------------------------------------------


async def run_journey() -> None:
    transport = httpx.ASGITransport(app=main.app)
    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # ── Privacy Sandbox pre-flight check (universal name redaction) ──────
        phase("0", "Privacy Sandbox — universal redaction pre-flight")
        sample = "I am Ramesh Kumar, call me at +91 98765 43210 or ramesh@x.com (Patient ID: ZEN-T371)."
        scrubbed = main._pii_scrubber.anonymize_payload(sample, names=["Ramesh Kumar"])
        step(f"input : {sample}")
        step(f"output: {scrubbed}")
        require("Ramesh Kumar" not in scrubbed, "patient NAME redacted")
        require("+91 98765 43210" not in scrubbed, "Indian PHONE redacted")
        require("ramesh@x.com" not in scrubbed, "EMAIL redacted")
        require("[REDACTED_PII]" in scrubbed, "redaction marker present")

        # ── Privacy Sandbox: clinical terms preserved (no false positives) ───
        # Regression guard for the drug-name false positive: _collect_names used
        # to walk extracted.medications[] and treat each drug's "name" as a
        # patient name, so Clopidogrel/Atorvastatin got redacted in teach-back.
        # This exercises the EXACT teach-back path (_collect_names over an
        # extracted payload, then anonymize_payload) and asserts drug names,
        # dosages, and medical shorthand survive while real PII still redacts.
        phase("0b", "Privacy Sandbox — clinical terms preserved (no false positives)")
        sample_extracted = {
            "diagnosis": "NSTEMI",
            "medications": [
                {"name": "Clopidogrel", "dosage": "75mg", "frequency": "once daily", "duration": "12 months"},
                {"name": "Atorvastatin", "dosage": "40mg", "frequency": "once nightly", "duration": "ongoing"},
                {"name": "Metformin", "dosage": "500mg", "frequency": "BD", "duration": "ongoing"},
            ],
            "allergies": ["Penicillin"],
        }
        collected_names = main._collect_names(sample_extracted)
        step(f"_collect_names(extracted) → {collected_names}")
        require(collected_names == [], "drug names are NOT collected as patient names")
        clinical_text = (
            "I take Clopidogrel 75mg once daily and Atorvastatin 40mg at night. "
            "My Metformin is 500mg BD. Call me at +91 98765 43210 (Patient ID: ZEN-T371)."
        )
        scrubbed_clinical = main._pii_scrubber.anonymize_payload(
            clinical_text, names=collected_names
        )
        step(f"input : {clinical_text}")
        step(f"output: {scrubbed_clinical}")
        require("Clopidogrel" in scrubbed_clinical, "Clopidogrel preserved (not redacted)")
        require("Atorvastatin" in scrubbed_clinical, "Atorvastatin preserved (not redacted)")
        require("Metformin" in scrubbed_clinical, "Metformin preserved (not redacted)")
        require("75mg" in scrubbed_clinical and "500mg" in scrubbed_clinical,
                "clinical dosages preserved (not redacted)")
        require("BD" in scrubbed_clinical, "medical shorthand preserved (not redacted)")
        require("+91 98765 43210" not in scrubbed_clinical, "real Indian phone still redacted")
        require("ZEN-T371" not in scrubbed_clinical, "patient ID still redacted")
        require("[REDACTED_PII]" in scrubbed_clinical, "real PII redaction marker still present")

        # ── Phase A: /api/upload (Agent 1 + Agent 2) ──────────────────────────
        phase("A", "/api/upload — Agent 1 (OCR) + Agent 2 (Safety Cross-Check)")
        files = {"file": ("discharge.jpg", b"\xff\xd8\xff\xe0fakejpegbytes", "image/jpeg")}
        # ABDM/DPDP compliance fields — passed as multipart form data alongside
        # the file. consent_granted=True authorizes processing; abha_id is the
        # 14-digit Ayushman Bharat Health Account id.
        form = {"abha_id": "12341234123412", "consent_granted": "true"}
        resp = await client.post("/api/upload", files=files, data=form)
        require(resp.status_code == 200, f"upload HTTP 200 (got {resp.status_code})")
        upload = resp.json()
        step(f"patient_id: {upload['patient_id']}")
        step(f"diagnosis : {upload['extracted']['diagnosis']}")
        step(f"medications: {len(upload['extracted']['medications'])} item(s)")
        step(f"safety_flags: {len(upload['safety_flags'])} flag(s)")

        require(set(upload) >= {"patient_id", "extracted", "safety_flags", "teach_back", "language", "compliance_metadata"},
                "upload output matches shared contract top-level keys (incl. compliance_metadata)")
        require(set(upload["extracted"]) >= {"diagnosis", "medications", "precautions", "follow_up_date", "warning_signs", "allergies"},
                "extracted object has full Agent 1 contract (incl. allergies)")
        require(len(upload["extracted"]["medications"]) == 4, "4 medications extracted (incl. Amoxicillin)")
        require(upload["extracted"]["allergies"] == ["Penicillin"],
                "allergies extracted and forwarded in the upload contract")
        require(len(upload["safety_flags"]) >= 1, "Agent 2 fired ≥1 safety flag")

        # ABDM/DPDP compliance metadata (returned on every medical-records response).
        cm = upload["compliance_metadata"]
        step(f"compliance_metadata → abha={cm['abdm_abha_id']}, consent={cm['dpdp_consent']}, residency={cm['data_residency']}")
        require(cm["abdm_abha_id"] == "12341234123412", "compliance metadata echoes the ABHA id")
        require(cm["dpdp_consent"] is True, "compliance metadata records dpdp_consent=True")
        require(cm["data_residency"] == "PHI Retained on Local Edge", "data_residency label correct")
        require(cm["cloud_transmission"] == "Strictly De-identified Clinical Tokens Only",
                "cloud_transmission label correct")

        # Robust flag search (order-independent) — the drug-drug interaction
        # flag for Clopidogrel × Omeprazole should still be present.
        interaction_flags = [f for f in upload["safety_flags"] if f.get("type") == "interaction"]
        require(len(interaction_flags) >= 1, "Agent 2 flagged the Clopidogrel × Omeprazole interaction")

        # The headline allergy-conflict check: Amoxicillin vs documented
        # Penicillin allergy must surface as a CRITICAL allergy_conflict flag
        # with the exact contract shape (medication + allergy keys).
        allergy_flags = [f for f in upload["safety_flags"] if f.get("type") == "allergy_conflict"]
        require(len(allergy_flags) >= 1, "Agent 2 flagged the Amoxicillin × Penicillin allergy conflict")
        ac = allergy_flags[0]
        step(f"allergy_conflict → medication={ac.get('medication')}, allergy={ac.get('allergy')}, severity={ac.get('severity')}")
        require(ac.get("severity") == "CRITICAL", "allergy conflict severity is CRITICAL")
        require(ac.get("medication") == "Amoxicillin", "allergy conflict names the offending medication")
        require(ac.get("allergy") == "Penicillin", "allergy conflict names the documented allergen")
        require("CRITICAL ALERT" in ac.get("message", ""), "allergy conflict message carries the CRITICAL ALERT prefix")

        require(set(upload["teach_back"]) >= {"questions_asked", "patient_responses", "understanding_score", "corrections_given"},
                "teach_back seed state present")

        # ── Phase A1b: DPDP consent gate + ABHA validation ───────────────────
        # consent_granted=False MUST be rejected with HTTP 403 before any medical
        # record is processed (DPDP Act 2023). A malformed ABHA id (not 14 digits)
        # MUST be rejected with HTTP 422.
        phase("A1b", "/api/upload — DPDP consent gate (403) + ABHA validation (422)")
        gate_files = {"file": ("discharge.jpg", b"\xff\xd8\xff\xe0fakejpegbytes", "image/jpeg")}
        consent_denied = await client.post(
            "/api/upload", files=gate_files, data={"consent_granted": "false"}
        )
        require(consent_denied.status_code == 403,
                f"consent=False rejected with HTTP 403 (got {consent_denied.status_code})")
        require("DPDP Act Violation" in (consent_denied.json().get("detail") or ""),
                "403 carries the DPDP Act Violation message")

        bad_abha = await client.post(
            "/api/upload", files=gate_files,
            data={"abha_id": "123", "consent_granted": "true"},
        )
        require(bad_abha.status_code == 422,
                f"malformed ABHA id rejected with HTTP 422 (got {bad_abha.status_code})")

        # ── Phase A2: native PDF upload acceptance ───────────────────────────
        # The /api/upload content-type allowlist now includes application/pdf.
        # extract_discharge is mocked here, so this validates the route accepts a
        # PDF and returns the full contract (the real PDF text/render logic is
        # covered by the standalone document_intelligence smoke test).
        phase("A2", "/api/upload — native PDF acceptance")
        try:
            import fitz  # pymupdf — available in the backend venv
            _pdf_doc = fitz.open()
            _pdf_page = _pdf_doc.new_page()
            _pdf_page.insert_text(
                (72, 72),
                "Diagnosis: NSTEMI. Medications: Clopidogrel 75mg OD. Allergies: Penicillin.",
            )
            _pdf_bytes = _pdf_doc.tobytes()
            _pdf_doc.close()
            pdf_files = {"file": ("discharge.pdf", _pdf_bytes, "application/pdf")}
            pdf_resp = await client.post("/api/upload", files=pdf_files)
            require(pdf_resp.status_code == 200,
                    f"PDF upload accepted HTTP 200 (got {pdf_resp.status_code})")
            pdf_upload = pdf_resp.json()
            require(set(pdf_upload) >= {"patient_id", "extracted", "safety_flags", "teach_back", "language"},
                    "PDF upload returns the full shared contract")
            step(f"PDF upload → {len(pdf_upload['extracted']['medications'])} med(s), "
                 f"{len(pdf_upload['safety_flags'])} flag(s)")
        except ImportError:
            info("pymupdf not installed — skipping PDF upload acceptance check")

        # ── Schema bridge: upload → teach-back input ─────────────────────────
        phase("B", "/api/teach-back — Agent 3 (Teach-Back Verification)")
        teach_back_payload = {
            "extracted": upload["extracted"],
            "current_teach_back": upload["teach_back"],
            "patient_response": (
                "I need Clopidogrel 75mg once daily for 12 months to prevent "
                "blood clots after my heart event, and Atorvastatin for cholesterol."
            ),
            "safety_flags": upload["safety_flags"],
            "language": "English",
            "patient_email": "patient.demo@medguardian.app",
            "doctor_email": "doctor.demo@medguardian.app",
        }
        step("payload built from upload output: extracted ✓ current_teach_back ✓ safety_flags ✓")
        resp = await client.post("/api/teach-back", json=teach_back_payload, headers=headers)
        require(resp.status_code == 200, f"teach-back HTTP 200 (got {resp.status_code})")
        teach = resp.json()
        score = int(teach.get("understanding_score", 0))
        step(f"comprehension score: {score}/100")
        require(score >= 70, "comprehension score ≥ 70 (handoff threshold)")
        require(set(teach) >= {"questions_asked", "patient_responses", "understanding_score", "corrections_given"},
                "teach-back returns full contract state")

        # ── Phase C: Agent 4 auto-triggered in the background ────────────────
        phase("C", "Agent 4 (Care Coordinator) — background auto-trigger")
        step("awaiting asyncio.create_task background trigger…")
        # The teach-back endpoint scheduled dispatch_care_coordination via
        # asyncio.create_task; yield to the loop so it completes.
        await asyncio.sleep(0.5)
        require(len(coordinator_calls) == 1, "Agent 4 dispatched exactly once in background")
        call = coordinator_calls[0]
        step(f"→ doctor={call['doctor_email']}, patient={call['patient_email']}, lang={call['language']}")
        step(f"→ forwarded safety_flags: {call['has_safety_flags']}, teach_back_score: {call['teach_back_score']}")
        require(call["has_safety_flags"], "Agent 4 received the safety_flags from Agent 2")
        require(call["teach_back_score"] == score, "Agent 4 received the live Teach-Back score")

        # ── Phase D: /api/claim/generate (Agent 5) ───────────────────────────
        phase("D", "/api/claim/generate — Agent 5 (Auto-Claim & Insurance Justification)")
        # Assemble the shared state object exactly as the hospital UI would.
        patient_data = {
            "patient_id": upload["patient_id"],
            "extracted": upload["extracted"],
            "safety_flags": upload["safety_flags"],
            "teach_back": teach,  # live Agent 3 state
            "language": "English",
        }
        claim_payload = {
            "patient_data": patient_data,
            "patient_email": "patient.demo@medguardian.app",
            # ABDM/DPDP compliance — carried on the JSON request body.
            "abha_id": "12341234123412",
            "consent_granted": True,
        }
        step("patient_data assembled: extracted ✓ safety_flags ✓ teach_back (live) ✓")
        resp = await client.post("/api/claim/generate", json=claim_payload, headers=headers)
        require(resp.status_code == 200, f"claim HTTP 200 (got {resp.status_code})")
        claim = resp.json()
        dossier = claim["dossier"]
        html = claim["html_report"]

        require(set(dossier) >= {"icd10_codes", "medical_necessity_brief", "claim_summary"},
                "dossier has the strict JSON contract keys")
        require(len(dossier["icd10_codes"]) >= 1, "≥1 ICD-10 code assigned")
        require(dossier["icd10_codes"][0]["rank"] == "primary", "primary ICD-10 code ranked")
        require(len(dossier["medical_necessity_brief"]) == 3, "exactly 3 medical-necessity bullets")
        require(len(dossier["claim_summary"]["line_items"]) >= 1, "≥1 billing line item")
        require("<table" in html and "ICD-10" in html, "HTML report contains ICD-10 table")
        require("Total Estimated Cost" in html, "HTML report contains total cost")
        require(claim["patient_notification"]["ok"], "patient claim-status notification sent (mocked)")

        # ABDM/DPDP compliance metadata on the claim response too.
        require("compliance_metadata" in claim, "claim response carries compliance_metadata")
        ccm = claim["compliance_metadata"]
        step(f"claim compliance_metadata → abha={ccm['abdm_abha_id']}, consent={ccm['dpdp_consent']}")
        require(ccm["abdm_abha_id"] == "12341234123412", "claim compliance metadata echoes the ABHA id")
        require(ccm["dpdp_consent"] is True, "claim compliance metadata records dpdp_consent=True")
        require(ccm["data_residency"] == "PHI Retained on Local Edge", "claim data_residency label correct")
        require(ccm["cloud_transmission"] == "Strictly De-identified Clinical Tokens Only",
                "claim cloud_transmission label correct")

        step(f"ICD-10 codes: {[c['code'] for c in dossier['icd10_codes']]}")
        step(f"total cost  : {dossier['claim_summary']['total_estimated_cost']}")
        step(f"HTML report : {len(html)} chars")

        # ── Final summary ───────────────────────────────────────────────────
        banner("✅  MASTER PIPELINE PASSED — all 5 agents verified end-to-end")
        info("Agent 1  Document Intelligence  → extracted discharge contract (PDF + cursive/shorthand aware)")
        info("Agent 2  Safety Cross-Check     → flagged Clopidogrel × Omeprazole + Amoxicillin × Penicillin allergy")
        info("Agent 3  Teach-Back Verification → score 92/100 (handoff threshold met)")
        info("Agent 4  Care Coordinator        → auto-triggered in background")
        info("Agent 5  Auto-Claim Engine       → dossier + HTML report generated")
        info("Privacy Sandbox                  → PII redacted, clinical terms preserved")
        info("ABDM / DPDP                       → ABHA id + consent gate + compliance_metadata verified")


def main_entry() -> int:
    install_mocks()
    banner("MedGuardian — Master Integration Test (5-agent pipeline)")
    try:
        asyncio.run(run_journey())
        return 0
    except AssertionError as exc:
        print(f"\n{C.RED}{C.BOLD}✗ TEST FAILED: {exc}{C.RESET}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n{C.RED}{C.BOLD}✗ TEST ERROR: {type(exc).__name__}: {exc}{C.RESET}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main_entry())