// frontend/services/api.ts
import axios, { isAxiosError } from 'axios';

// Backend API origin. In development this defaults to the local FastAPI server.
// In production (and for real mobile devices, which cannot reach your dev
// machine's localhost) set NEXT_PUBLIC_API_BASE_URL to the deployed backend
// origin, e.g. https://medguardian-api.up.railway.app. A trailing slash is
// tolerated and stripped. Every call site below builds on `API_BASE`, so this
// is the single place to re-point the frontend at a different backend.
const API_ORIGIN =
  (process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000').replace(/\/+$/, '');
const API_BASE = `${API_ORIGIN}/api`;

// ---------------------------------------------------------------------------
// Shared domain types — the MedGuardian JSON contract (context.md).
// Single source of truth for the extracted discharge payload, safety flags,
// teach-back state, and compliance metadata. Imported by every component so
// no `any` is needed to describe the pipeline state.
// ---------------------------------------------------------------------------

/** A single medication extracted by Agent 1. */
export interface Medication {
  name: string;
  dosage?: string;
  frequency?: string;
  duration?: string;
}

/** The structured discharge summary (Agent 1 output → Agent 2/3/4/5 input). */
export interface ExtractedData {
  diagnosis: string;
  medications: Medication[];
  precautions: string[];
  follow_up_date: string;
  warning_signs: string[];
  allergies?: string[];
}

/** Drug-drug interaction / duplicate / dosage flag from Agent 2. */
export interface InteractionSafetyFlag {
  type: 'interaction' | 'duplicate' | 'dosage_anomaly';
  medications_involved?: string[];
  severity: 'low' | 'medium' | 'high';
  message: string;
}

/** Allergy cross-reference flag (CRITICAL) from Agent 2. */
export interface AllergyConflictSafetyFlag {
  type: 'allergy_conflict';
  severity: 'CRITICAL';
  message: string;
  medication: string;
  allergy: string;
}

/** Discriminated union of all safety flag shapes (context.md). */
export type SafetyFlag = InteractionSafetyFlag | AllergyConflictSafetyFlag;

/** Teach-back session state (Agent 3). */
export interface TeachBackState {
  questions_asked: string[];
  patient_responses: string[];
  understanding_score: number;
  corrections_given: string[];
}

/** ABDM / DPDP Act 2023 compliance metadata attached to medical-records responses. */
export interface ComplianceMeta {
  abdm_abha_id: string | null;
  dpdp_consent: boolean;
  data_residency: string;
  cloud_transmission: string;
}

/** Full /api/upload contract state object. */
export interface UploadResponse {
  patient_id: string;
  extracted: ExtractedData;
  safety_flags: SafetyFlag[];
  teach_back: TeachBackState;
  language: string;
  compliance_metadata?: ComplianceMeta;
}

/** An ICD-10 / diagnosis code entry in a claim dossier. */
export interface ClaimCode {
  code: string;
  description?: string;
}

/** Agent 5 claim dossier. The backend may return the same data under several
 *  key spellings (icd10_codes / icd_10_codes / icd_codes …), hence the index
 *  signature for the fields the UI does not individually render. */
export interface ClaimDossier {
  icd10_codes?: ClaimCode[];
  icd_10_codes?: ClaimCode[];
  icd_codes?: ClaimCode[];
  diagnosis_codes?: ClaimCode[];
  claim_summary?: { total_estimated_cost?: string | number };
  estimated_reimbursement?: number;
  total_estimated_cost?: number;
  billing?: { total: number };
  claim_total?: number;
  [key: string]: unknown;
}

/** Result of /api/claim/generate. */
export interface ClaimResult {
  dossier: ClaimDossier;
  html_report: string;
  patient_notification?: unknown;
  compliance_metadata?: ComplianceMeta;
  [key: string]: unknown;
}

/** Shared pipeline state passed to Agent 4 (Care Coordinator). */
export interface PatientData {
  patient_id?: string;
  extracted: ExtractedData;
  safety_flags: SafetyFlag[];
  teach_back: TeachBackState;
  language?: string;
}

/** Agent 4 care-coordinator dispatch result. */
export interface CoordinatorResult {
  status: string;
  detail: string;
  [key: string]: unknown;
}

/**
 * Narrow an unknown caught value into a safe user-facing message, preferring
 * the backend's `detail`/`message` from an Axios error response. Replaces the
 * `catch (err: any) { err?.response?.data?.detail … }` anti-pattern across
 * the app without resorting to `any`.
 */
export function getApiErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const data = err.response?.data as
      | { detail?: unknown; message?: unknown; error?: unknown }
      | undefined;
    const detail = data?.detail ?? data?.message ?? data?.error;
    if (typeof detail === 'string' && detail) return detail;
    if (err.message) return err.message;
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

// 0. Document Upload / OCR Intake (Agent 1)
export interface UploadOptions {
  /** 14-digit Ayushman Bharat Health Account id (ABDM). Required by backend. */
  abhaId?: string;
  /** DPDP Act 2023 consent gate. Backend rejects with 403 unless true. */
  consentGranted?: boolean;
}

export const uploadDocument = async (
  file: File,
  opts: UploadOptions = {},
): Promise<UploadResponse> => {
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
  //
  // Identity linkage: if a Supabase session is in localStorage we attach the
  // bearer token so the backend can upsert the authenticated user into the
  // ``patients`` table (Admin Command Center cohort). The upload still
  // succeeds when no session is present — the demo flow stays anonymous.
  const headers = authHeaders();
  const response = await axios.post<UploadResponse>(
    `${API_BASE}/upload`,
    formData,
    Object.keys(headers).length ? { headers } : undefined,
  );
  // Returns the full contract state object:
  // { patient_id, extracted, safety_flags, teach_back, language, compliance_metadata }
  return response.data;
};

// 1. Safety Check
export const checkSafety = async (medications: Medication[]): Promise<SafetyFlag[]> => {
  const response = await axios.post<{ safety_flags: SafetyFlag[] }>(
    `${API_BASE}/safety-check`,
    { medications },
  );
  return response.data.safety_flags;
};

// 2. Teach-Back Verification
export const evaluateTeachBack = async (
  extracted: ExtractedData,
  currentTeachBack: Partial<TeachBackState>,
  patientResponse: string,
): Promise<TeachBackState> => {
  // Send the validated Supabase user id as patient_id so the backend can re-read
  // the patient's LATEST discharge summary from Supabase on every message and
  // overlay it onto `extracted` before the LLM runs. This is the frontend half
  // of the "stale Metformin" fix — without it the backend overlay no-ops and
  // the LLM is grounded in whatever `extracted` the chat happened to hold.
  // Falls back to undefined (anonymous/demo flow) so the chat still works
  // without a signed-in user.
  let patient_id: string | undefined;
  if (typeof window !== 'undefined') {
    try {
      const raw = window.localStorage.getItem('medguardian_session');
      if (raw) {
        const session = JSON.parse(raw) as AuthSession;
        patient_id = session.user_id || undefined;
      }
    } catch {
      // malformed session — proceed without patient_id
    }
  }
  const response = await axios.post<TeachBackState>(`${API_BASE}/teach-back`, {
    extracted,
    current_teach_back: currentTeachBack,
    patient_response: patientResponse,
    patient_id,
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
export const textToSpeech = async (text: string, language: string = 'en'): Promise<string> => {
  const response = await axios.post<{ audio_base64: string }>(`${API_BASE}/voice/tts`, {
    text,
    language,
  });
  return response.data.audio_base64; // Use this in an <audio src="data:audio/wav;base64,..."> tag
};

export const speechToText = async (audioBlob: Blob): Promise<string> => {
  const formData = new FormData();
  formData.append('file', audioBlob, 'recording.wav');
  // Do NOT set Content-Type manually — the browser must add the multipart boundary.
  const response = await axios.post<{ text: string }>(`${API_BASE}/voice/stt`, formData);
  return response.data.text;
};

// 4. Agent 4 — Care Coordinator (manual override; also auto-fires from teach-back)
export const triggerCoordinator = async (
  patientData: PatientData,
  patientEmail: string,
  doctorEmail: string,
  language: string = 'English',
): Promise<CoordinatorResult> => {
  const response = await axios.post<CoordinatorResult>(`${API_BASE}/coordinator/trigger`, {
    patient_data: patientData,
    patient_email: patientEmail,
    doctor_email: doctorEmail,
    language,
  });
  return response.data;
};

// 5. Agent 5 — Auto-Claim & Insurance Justification Engine
export interface ClaimOptions {
  /** 14-digit Ayushman Bharat Health Account id. Required by backend (403 if absent). */
  abhaId?: string;
  /** DPDP Act 2023 consent gate. Backend rejects with 403 unless true. */
  consentGranted?: boolean;
}

export const generateClaimDossier = async (
  patientData: PatientData,
  patientEmail: string,
  opts: ClaimOptions = {},
): Promise<ClaimResult> => {
  // Returns { dossier, html_report, patient_notification, compliance_metadata }.
  // The backend always returns a dossier (with a review-flagged fallback if the
  // coding LLM is unavailable), so the UI can always render an html_report.
  //
  // ABDM / DPDP Act 2023 compliance: consent_granted must be true (else HTTP
  // 403) and abha_id is validated as 14 digits. Defaults keep the legacy demo
  // path working when called without options; the Admin Console passes the
  // selected patient's real ABHA id.
  const response = await axios.post<ClaimResult>(`${API_BASE}/claim/generate`, {
    patient_data: patientData,
    patient_email: patientEmail,
    consent_granted: opts.consentGranted ?? true,
    abha_id: opts.abhaId ?? '12341234123412',
  });
  return response.data;
};

/**
 * Download the Claim Summary Report as a real, selectable-text PDF.
 *
 * Why server-side (not html2pdf.js / jspdf + html2canvas):
 *   * The dossier is already generated server-side by `/api/claim/generate`;
 *     re-rendering it as text on the server avoids a 1.5MB client bundle
 *     (MedGuardian runs on mobile for elderly patients) AND keeps the output
 *     as REAL selectable text, not a rasterized screenshot of styled DOM.
 *   * The backend re-runs `generate_claim_dossier` so the PDF reflects the
 *     SAME JSON output the hospital would have received — never trust a
 *     client-supplied dossier.
 *
 * The backend's `Content-Disposition: attachment; filename="..."` header
 * triggers the browser's native Save dialog. We additionally anchor an
 * invisible `<a>` and click it as a defensive fallback for browsers that
 * ignore the header (rare, but safer than relying on the header alone).
 * The anchor is removed from the DOM immediately after, so the modal stays
 * interactive and the download is fully decoupled from React state.
 *
 * Returns the filename so the caller can show a toast like "Saved as
 * medguardian-claim-...pdf" without re-parsing the header.
 */
export const downloadClaimPDF = async (
  patientData: PatientData,
  patientEmail: string,
  opts: ClaimOptions = {},
): Promise<string> => {
  const response = await axios.post<Blob>(
    `${API_BASE}/claim/pdf`,
    {
      patient_data: patientData,
      patient_email: patientEmail,
      consent_granted: opts.consentGranted ?? true,
      abha_id: opts.abhaId ?? '12341234123412',
    },
    {
      responseType: 'blob',
      // The PDF route re-runs the LLM, so give it the same generous timeout
      // as `syncReminders` (30s) — the bottleneck is OpenRouter, not us.
      timeout: 30000,
    },
  );

  // Parse the filename out of Content-Disposition; fall back to a sensible
  // default so a misconfigured proxy doesn't crash the download UX.
  const header = (response.headers['content-disposition'] ?? response.headers['Content-Disposition']) as
    | string
    | undefined;
  let filename = 'medguardian-claim-dossier.pdf';
  if (header) {
    const match = /filename="?([^";]+)"?/.exec(header);
    if (match && match[1]) filename = match[1];
  }

  // Defensive download: some browsers honor Content-Disposition natively
  // (the modern path), others require an explicit <a download> click. We do
  // BOTH — the inline <a> is appended, clicked, and removed in the same
  // microtask, so it never appears in the React tree or affects layout.
  const blob = response.data;
  const url = window.URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.rel = 'noopener';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    // Give the browser one tick to start the download before tearing down.
    await new Promise((resolve) => setTimeout(resolve, 0));
    a.remove();
  } finally {
    window.URL.revokeObjectURL(url);
  }

  return filename;
};

// ---------------------------------------------------------------------------
// 6. Auth Gateway — Supabase-backed login / register.
//
// Email/password requests use the real backend and never fall back to a mock
// session. The separate Google demo remains deferred to Task 3B-3.
// ---------------------------------------------------------------------------

export type AuthRole = 'patient' | 'admin';

export interface AuthSession {
  token: string;
  role: AuthRole;
  email: string;
  name: string;
  // Validated Supabase auth uid. Populated from /api/auth/login + /api/auth/me
  // so client-side flows that need the server-side user id (e.g. sending
  // patient_id to /api/teach-back for the fresh-prescription overlay) can read
  // it from the persisted session without a extra round-trip.
  user_id?: string;
  abha_id?: string;
  email_confirmation_required?: boolean;
  mock?: boolean;
}

interface AuthPayload {
  email: string;
  password: string;
  role: AuthRole;
  name?: string;
}

/** Raw backend auth response (Supabase-backed AuthResponse). */
interface AuthBackendResponse {
  access_token?: string;
  token?: string;
  user_id?: string;
  email?: string;
  name?: string;
  role?: string;
  abha_id?: string | null;
  email_confirmation_required?: boolean;
}

async function authRequest(path: string, payload: AuthPayload): Promise<AuthSession> {
  const response = await axios.post<AuthBackendResponse>(`${API_BASE}/auth/${path}`, payload, {
    timeout: 10000,
  });
  const d: AuthBackendResponse = response.data ?? {};
  const accessToken = d.access_token || d.token;

  if (!accessToken && !d.email_confirmation_required) {
    throw new Error('Authentication did not return an access token.');
  }

  return {
    token: accessToken || '',
    role: (d.role || 'patient') as AuthRole,
    email: d.email || payload.email,
    name: d.name || payload.email.split('@')[0],
    user_id: d.user_id || undefined,
    abha_id: d.abha_id ?? undefined,
    email_confirmation_required: Boolean(d.email_confirmation_required),
    mock: false,
  };
}

export const authLogin = (payload: AuthPayload) => authRequest('login', payload);
export const authRegister = (payload: AuthPayload) => authRequest('register', payload);

// ---------------------------------------------------------------------------
// 7b. /api/auth/me — server-resolved identity for an existing Supabase token.
//
// The Google OAuth callback sends the Supabase access token (obtained after
// the PKCE exchange) here; the backend validates it and returns the role the
// SERVER resolved from ADMIN_EMAILS. The frontend therefore never decides
// admin status — an allowlisted email is routed to /admin, everyone else to
// /patient, exactly like the email/password flow.
// ---------------------------------------------------------------------------

export interface AuthMe {
  user_id: string;
  email: string;
  role: AuthRole;
  name: string;
}

export const getMe = async (accessToken: string): Promise<AuthMe> => {
  const response = await axios.get<AuthMe>(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    timeout: 8000,
  });
  return response.data;
};

// ---------------------------------------------------------------------------
// 7. Hospital Admin — patient registry for the command-center data grid.
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
  extracted: ExtractedData;
  safety_flags: SafetyFlag[];
}

export interface PatientsResponse {
  patients: PatientRecord[];
  source: 'supabase' | 'unconfigured';
  count: number;
}

interface PatientsRawResponse {
  patients?: PatientRecord[];
  source?: string;
  count?: number;
}

export const getPatients = async (): Promise<PatientsResponse> => {
  // The cohort listing is admin-only on the backend (require_admin). The
  // caller's Supabase access token is attached so the server can authorize
  // the request against the ADMIN_EMAILS allowlist. Without it the backend
  // returns 401; a non-admin token returns 403.
  const headers: Record<string, string> = authHeaders();
  const hasAuthHeader = Boolean(headers.Authorization);
  // DIAGNOSTIC: confirm the Authorization header is actually travelling
  // with the request, and log every response / error so we can bisect
  // "Access Denied" (401/403) from "Data Not Found" (200 with empty list).
  // eslint-disable-next-line no-console
  console.log(
    '[medguardian.diag] getPatients: sending GET /api/patients',
    {
      hasAuthHeader,
      tokenPrefix: hasAuthHeader
        ? String(headers.Authorization).slice(0, 16) + '…'
        : '<none>',
    },
  );
  try {
    const response = await axios.get<PatientsRawResponse>(`${API_BASE}/patients`, {
      headers,
      timeout: 6000,
    });
    // eslint-disable-next-line no-console
    console.log('[medguardian.diag] getPatients: 2xx response', {
      status: response.status,
      body: response.data,
    });
    const data: PatientsRawResponse = response.data ?? {};
    return {
      patients: (data.patients ?? []) as PatientRecord[],
      source: (data.source ?? 'unconfigured') as 'supabase' | 'unconfigured',
      count: data.count ?? (data.patients?.length ?? 0),
    };
  } catch (err) {
    if (isAxiosError(err)) {
      // eslint-disable-next-line no-console
      console.error('[medguardian.diag] getPatients: error response', {
        status: err.response?.status,
        statusText: err.response?.statusText,
        body: err.response?.data,
        message: err.message,
      });
    } else {
      // eslint-disable-next-line no-console
      console.error('[medguardian.diag] getPatients: non-axios throw', err);
    }
    throw err;
  }
};

// ---------------------------------------------------------------------------
// 8. Google Calendar connection + medication reminders (real endpoints).
//
// These call the real backend routes (/api/calendar/google/*,
// /api/calendar/reminders/*). No refresh token, access token, client secret,
// or service-role key is ever held in the browser — only the short-lived
// Supabase access token used for all authenticated requests, sent via
// Authorization header.
// ---------------------------------------------------------------------------

/** Safe Google Calendar connection metadata returned by /status (no tokens). */
export interface CalendarConnection {
  id: string;
  user_id: string;
  provider: string;
  google_account_email?: string;
  calendar_id: string;
}

export interface CalendarStatus {
  connected: boolean;
  profile: CalendarConnection | null;
}

export interface ReminderTimeSpec {
  time: string;
  label: string;
}

/** One persisted medication reminder row (no token material). */
export interface CalendarReminder {
  id: string;
  medication_name: string;
  dosage?: string;
  frequency?: string;
  schedule: ReminderTimeSpec[];
  google_event_ids: string[];
  status: 'active' | 'skipped' | 'error' | 'disconnected';
  needs_review: boolean;
  recurring: boolean;
  start_date: string;
  end_date?: string;
  timezone: string;
}

export interface ReminderListResponse {
  reminders: CalendarReminder[];
  count: number;
}

export interface ReminderSyncResponse {
  synced: number;
  skipped: number;
  errors: number;
  reminders: MedicationSyncOutcome[];
}

export interface MedicationSyncOutcome {
  medication_name: string;
  status: 'active' | 'skipped' | 'error';
  needs_review: boolean;
  recurring: boolean;
  schedule: ReminderTimeSpec[];
  error?: string | null;
}

/** One medication to sync to Google Calendar reminders. */
export interface ReminderMedication {
  name: string;
  dosage?: string;
  frequency?: string;
  duration?: string;
}

/** True when the Authorization header should be attached (browser-only session). */
function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const raw = window.localStorage.getItem('medguardian_session');
  if (!raw) {
    // eslint-disable-next-line no-console
    console.log(
      '[medguardian.diag] authHeaders: no medguardian_session in localStorage',
    );
    return {};
  }
  try {
    const session = JSON.parse(raw) as AuthSession;
    // DIAGNOSTIC: the empty-token case is the most common cause of 401s on
    // /api/patients. The header is rebuilt per request, so logging once per
    // call is fine — it tells us whether the session envelope is malformed
    // (token missing) or the session simply isn't persisted yet.
    // eslint-disable-next-line no-console
    console.log('[medguardian.diag] authHeaders', {
      role: session.role,
      email: session.email,
      tokenPresent: Boolean(session.token),
      tokenPrefix: session.token ? session.token.slice(0, 12) + '…' : '<none>',
    });
    if (!session.token) return {};
    return { Authorization: `Bearer ${session.token}` };
  } catch {
    // eslint-disable-next-line no-console
    console.warn(
      '[medguardian.diag] authHeaders: malformed medguardian_session JSON',
    );
    return {};
  }
}

export const getCalendarStatus = async (): Promise<CalendarStatus> => {
  const response = await axios.get<CalendarStatus>(
    `${API_BASE}/calendar/google/status`,
    { headers: authHeaders(), timeout: 8000 },
  );
  return response.data;
};

/** Returns the Google consent URL the frontend navigates to (full-page redirect).
 *
 *  The backend (`/api/calendar/google/connect`) returns `{ authorization_url }`
 *  when Google OAuth is configured, or 503 when it isn't (caught as an Axios
 *  error by the caller). We additionally validate the body here so that an
 *  unexpected/empty response can never resolve to `undefined` — which would
 *  otherwise send the browser to `localhost:3000/undefined` via
 *  `window.location.href = undefined`. A missing URL throws a clean message
 *  the connection card renders verbatim instead of redirecting.
 */
export const connectGoogleCalendar = async (): Promise<string> => {
  const response = await axios.get<{ authorization_url?: string }>(
    `${API_BASE}/calendar/google/connect`,
    { headers: authHeaders(), timeout: 8000 },
  );
  const url = response.data?.authorization_url;
  if (!url || typeof url !== 'string' || url.trim() === '') {
    throw new Error('Google Calendar is not configured on the backend. Ask your administrator to set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET.');
  }
  return url;
};

export const disconnectGoogleCalendar = async (): Promise<boolean> => {
  const response = await axios.delete<{ disconnected: boolean }>(
    `${API_BASE}/calendar/google/disconnect`,
    { headers: authHeaders(), timeout: 8000 },
  );
  return Boolean(response.data.disconnected);
};

export const syncReminders = async (
  medications: ReminderMedication[],
  timezone: string,
  patientId?: string,
): Promise<ReminderSyncResponse> => {
  const response = await axios.post<ReminderSyncResponse>(
    `${API_BASE}/calendar/reminders/sync`,
    { medications, timezone, patient_id: patientId ?? null },
    { headers: authHeaders(), timeout: 30000 },
  );
  return response.data;
};

export const getReminders = async (): Promise<ReminderListResponse> => {
  const response = await axios.get<ReminderListResponse>(
    `${API_BASE}/calendar/reminders`,
    { headers: authHeaders(), timeout: 8000 },
  );
  return response.data;
};

export const deleteReminder = async (reminderId: string): Promise<void> => {
  await axios.delete(`${API_BASE}/calendar/reminders/${reminderId}`, {
    headers: authHeaders(),
    timeout: 8000,
  });
};