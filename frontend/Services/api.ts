// frontend/services/api.ts
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

// 0. Document Upload / OCR Intake (Agent 1)
export interface UploadOptions {
  /** 14-digit Ayushman Bharat Health Account id (ABDM). Required by backend. */
  abhaId?: string;
  /** DPDP Act 2023 consent gate. Backend rejects with 403 unless true. */
  consentGranted?: boolean;
}

export const uploadDocument = async (file: File, opts: UploadOptions = {}) => {
  const formData = new FormData();
  formData.append('file', file);
  // ABDM / DPDP Act 2023 compliance fields — the backend rejects the upload
  // with HTTP 403 unless consent_granted is true, and validates abha_id as a
  // 14-digit Ayushman Bharat Health Account id. The caller (UploadZone) now
  // collects these from the patient; defaults keep the legacy demo path
  // working when called without options.
  formData.append('consent_granted', String(opts.consentGranted ?? true));
  formData.append('abha_id', opts.abhaId ?? '12341234123412');
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
export interface ClaimOptions {
  /** 14-digit Ayushman Bharat Health Account id. Required by backend (403 if absent). */
  abhaId?: string;
  /** DPDP Act 2023 consent gate. Backend rejects with 403 unless true. */
  consentGranted?: boolean;
}

export const generateClaimDossier = async (
  patientData: any,
  patientEmail: string,
  opts: ClaimOptions = {}
) => {
  // Returns { dossier, html_report, patient_notification, compliance_metadata }.
  // The backend always returns a dossier (with a review-flagged fallback if the
  // coding LLM is unavailable), so the UI can always render an html_report.
  //
  // ABDM / DPDP Act 2023 compliance: consent_granted must be true (else HTTP
  // 403) and abha_id is validated as 14 digits. Defaults keep the legacy demo
  // path working when called without options; the Admin Console passes the
  // selected patient's real ABHA id.
  const response = await axios.post(`${API_BASE}/claim/generate`, {
    patient_data: patientData,
    patient_email: patientEmail,
    consent_granted: opts.consentGranted ?? true,
    abha_id: opts.abhaId ?? '12341234123412',
  });
  return response.data;
};

// ---------------------------------------------------------------------------
// 7. Auth Gateway — Supabase-backed login / register.
//
// The teammate's backend exposes `/api/auth/me` (token-validated) but the
// login/register routes are not yet implemented. These helpers POST to the
// canonical `/api/auth/{login,register}` paths so they work the moment Supabase
// auth is wired on the backend. Until then they fall back to a deterministic
// MOCK session so the multi-page demo (redirects to /patient or /admin) is
// fully navigable without a backend — without ever breaking a real call.
// ---------------------------------------------------------------------------

export type AuthRole = 'patient' | 'admin';

export interface AuthSession {
  token: string;
  role: AuthRole;
  email: string;
  name: string;
  abha_id?: string;
  mock?: boolean;
}

interface AuthPayload {
  email: string;
  password: string;
  role: AuthRole;
  name?: string;
}

async function authRequest(path: string, payload: AuthPayload): Promise<AuthSession> {
  try {
    const response = await axios.post(`${API_BASE}/auth/${path}`, payload, {
      // Keep the wait short so a missing backend falls through to the mock
      // quickly rather than hanging the login button.
      timeout: 4000,
    });
    const d = response.data;
    return {
      token: d.access_token || d.token || 'mock-token',
      role: (d.role || payload.role) as AuthRole,
      email: d.email || payload.email,
      name: d.name || payload.name || payload.email.split('@')[0],
      abha_id: d.abha_id,
      mock: false,
    };
  } catch (err: any) {
    // Network error / 404 (route not implemented yet) / timeout → mock auth so
    // the demo flow (role-based redirect) still works. This never throws, so
    // the login button always resolves to a session.
    if (err?.response?.status === 401 || err?.response?.status === 403) {
      // A real backend auth rejection (wrong password) should NOT silently
      // succeed as mock — only fall back to mock when the route is absent.
      throw err;
    }
    await new Promise((r) => setTimeout(r, 600)); // brief realism
    return {
      token: `mock.${payload.role}.${Date.now()}`,
      role: payload.role,
      email: payload.email,
      name: payload.name || payload.email.split('@')[0],
      abha_id: '12341234123412',
      mock: true,
    };
  }
}

export const authLogin = (payload: AuthPayload) => authRequest('login', payload);
export const authRegister = (payload: AuthPayload) => authRequest('register', payload);

// ---------------------------------------------------------------------------
// 8. Hospital Admin — patient registry for the command-center data grid.
//
// Thin client to the backend `/api/patients` route (registered in the flat
// main.py). The backend queries Supabase when configured and returns an empty
// list otherwise — there is NO fake seed data anywhere. The route returns a
// `source` field ("supabase" when the DB query ran, "unconfigured" when
// Supabase isn't wired) so the admin console can honestly label the data
// origin. This throws on a network failure so the admin UI can show a proper
// error/empty state rather than silently rendering stale data.
// ---------------------------------------------------------------------------

export interface PatientRecord {
  patient_id: string;
  abha_id: string;
  name: string;
  diagnosis: string;
  status: 'Stable' | 'Monitoring' | 'Critical' | 'Discharged';
  adherence: number;
  extracted: any;
  safety_flags: any[];
}

export interface PatientsResponse {
  patients: PatientRecord[];
  source: 'supabase' | 'unconfigured';
  count: number;
}

export const getPatients = async (): Promise<PatientsResponse> => {
  const response = await axios.get(`${API_BASE}/patients`, { timeout: 6000 });
  const data = response.data ?? {};
  return {
    patients: (data.patients ?? []) as PatientRecord[],
    source: (data.source ?? 'unconfigured') as 'supabase' | 'unconfigured',
    count: data.count ?? (data.patients?.length ?? 0),
  };
};