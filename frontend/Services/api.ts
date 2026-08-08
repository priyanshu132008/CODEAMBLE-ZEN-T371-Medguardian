// frontend/services/api.ts
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

// 0. Document Upload / OCR Intake (Agent 1)
export const uploadDocument = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  // ABDM / DPDP Act 2023 compliance fields — the backend rejects the upload
  // with HTTP 403 unless consent_granted is true, and validates abha_id as a
  // 14-digit Ayushman Bharat Health Account id. A mock ABHA id is sent for the
  // demo so the compliance gate passes and the response carries
  // compliance_metadata for the UI to display.
  formData.append('consent_granted', 'true');
  formData.append('abha_id', '12341234123412');
  // IMPORTANT: do NOT set Content-Type manually. The browser must set
  // "multipart/form-data; boundary=..." itself — a manual header omits the
  // boundary and the server rejects the body with 400 "Missing boundary".
  const response = await axios.post(`${API_BASE}/upload`, formData);
  // Returns the full contract state object:
  // { patient_id, extracted, safety_flags, teach_back, language, compliance_metadata }
  return response.data;
};

// 1. Safety Check
export const checkSafety = async (medications: any[]) => {
  const response = await axios.post(`${API_BASE}/safety-check`, { medications });
  return response.data.safety_flags;
};

// 2. Teach-Back Verification
export const evaluateTeachBack = async (
  extracted: any,
  currentTeachBack: any,
  patientResponse: string
) => {
  const response = await axios.post(`${API_BASE}/teach-back`, {
    extracted,
    current_teach_back: currentTeachBack,
    patient_response: patientResponse,
    // Hardcoded verified delivery address for the Agent 4 auto-trigger. In
    // Resend sandbox mode the sandbox sender (resend.dev) may only deliver to
    // the account owner's verified address, so both the patient + doctor
    // handoff copies route to the same verified inbox for the live demo.
    patient_email: 'priyanshucreator3@gmail.com',
    doctor_email: 'priyanshucreator3@gmail.com',
  });
  return response.data; // Returns updated teach_back object
};

// 3. Voice I/O
export const textToSpeech = async (text: string, language: string = 'en') => {
  const response = await axios.post(`${API_BASE}/voice/tts`, { text, language });
  return response.data.audio_base64; // Use this in an <audio src="data:audio/wav;base64,..."> tag
};

export const speechToText = async (audioBlob: Blob) => {
  const formData = new FormData();
  formData.append('file', audioBlob, 'recording.wav');
  // Do NOT set Content-Type manually — the browser must add the multipart boundary.
  const response = await axios.post(`${API_BASE}/voice/stt`, formData);
  return response.data.text;
};

// 4. Mock Endpoints (For UI Design)
export const getMockReminders = async () => {
  const response = await axios.get(`${API_BASE}/reminders/simulate`);
  return response.data.thread;
};

export const simulateEscalation = async (symptom: string) => {
  const response = await axios.post(`${API_BASE}/escalate/simulate`, { symptom });
  return response.data;
};

// 5. Agent 4 — Care Coordinator (manual override; also auto-fires from teach-back)
export const triggerCoordinator = async (
  patientData: any,
  patientEmail: string,
  doctorEmail: string,
  language: string = 'English'
) => {
  const response = await axios.post(`${API_BASE}/coordinator/trigger`, {
    patient_data: patientData,
    patient_email: patientEmail,
    doctor_email: doctorEmail,
    language,
  });
  return response.data;
};

// 6. Agent 5 — Auto-Claim & Insurance Justification Engine
export const generateClaimDossier = async (patientData: any, patientEmail: string) => {
  // Returns { dossier, html_report, patient_notification, compliance_metadata }.
  // The backend always returns a dossier (with a review-flagged fallback if the
  // coding LLM is unavailable), so the UI can always render an html_report.
  //
  // ABDM / DPDP Act 2023 compliance: consent_granted must be true (else HTTP
  // 403) and abha_id is validated as 14 digits. A mock ABHA id is sent for the
  // demo so the compliance gate passes and the response carries
  // compliance_metadata for the UI to display.
  const response = await axios.post(`${API_BASE}/claim/generate`, {
    patient_data: patientData,
    patient_email: patientEmail,
    consent_granted: true,
    abha_id: '12341234123412',
  });
  return response.data;
};