// frontend/services/api.ts
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

// 0. Document Upload / OCR Intake (Agent 1)
export const uploadDocument = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  // IMPORTANT: do NOT set Content-Type manually. The browser must set
  // "multipart/form-data; boundary=..." itself — a manual header omits the
  // boundary and the server rejects the body with 400 "Missing boundary".
  const response = await axios.post(`${API_BASE}/upload`, formData);
  // Returns the full contract state object: { patient_id, extracted, safety_flags, teach_back, language }
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
    patient_response: patientResponse
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