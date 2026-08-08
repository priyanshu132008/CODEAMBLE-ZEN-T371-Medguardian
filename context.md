# MedGuardian Architecture & Hackathon Context

## 1. The Problem & Solution
Patients leave hospitals with complex handwritten instructions. Poor discharge communication drives preventable readmissions (medication non-adherence raises risk by 34%). 
MedGuardian is a multi-agent AI companion that acts like a discharge nurse: it extracts instructions, checks safety, explains them in regional languages, verifies comprehension via "Teach-Back," and monitors symptoms. 

## 2. System Architecture & 5 Agents
- **Frontend**: Next.js web app (upload document, view results, teach-back chat).
- **Backend**: FastAPI orchestrating 5 specific agents:
  - **Agent 1 (Document Intelligence)**: Claude vision extracts messy handwriting to structured JSON.
  - **Agent 2 (Safety Cross-Check)**: Rule-based lookup against a CSV to find drug interactions and duplicates.
  - **Agent 3 (Teach-Back Verification)**: Explains instructions, asks patient to repeat them, and uses LLM to judge actual understanding (not just keyword matching).
  - **Agent 4 (Adherence Follow-Up)**: Simulated for this phase (mocked WhatsApp UI).
  - **Agent 5 (Symptom Escalation)**: Simulated for this phase. Escalates ONLY against the warning signs explicitly listed by the doctor on the discharge sheet.

## 3. The Shared JSON Contract (CRITICAL)
Every endpoint must conform to this exact state object.
```json
{
  "patient_id": "string",
  "extracted": {
    "diagnosis": "string",
    "medications": [
      {"name": "string", "dosage": "string", "frequency": "string", "duration": "string"}
    ],
    "precautions": ["string"],
    "follow_up_date": "string",
    "warning_signs": ["string"]
  },
  "safety_flags": [
    {
      "type": "interaction | duplicate | dosage_anomaly",
      "medications_involved": ["string"],
      "severity": "low | medium | high",
      "message": "string"
    }
  ],
  "teach_back": {
    "questions_asked": ["string"],
    "patient_responses": ["string"],
    "understanding_score": 0,
    "corrections_given": ["string"]
  },
  "language": "hi | mr | en"
}