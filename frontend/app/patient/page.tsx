'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { HeartPulse, ArrowLeft, Activity } from 'lucide-react';
import SafetyBanner from '@/Components/SafetyBanner';
import Dashboard from '@/Components/Dashboard';
import TeachBackChat, { type TeachBackChatHandle } from '@/Components/TeachBackChat';
import ScrollReveal from '@/Components/ScrollReveal';
import UploadZone from '@/Components/UploadZone';
import CriticalAlert from '@/Components/CriticalAlert';
import ComprehensionRing from '@/Components/ComprehensionRing';
import MedicationReminders from '@/Components/MedicationReminders';
import LogoutButton from '@/Components/LogoutButton';
import PWAInstallButton from '@/Components/PWAInstallButton';
import { Badge } from '@/Components/ui/badge';
import type {
  ExtractedData,
  TeachBackState,
  UploadResponse,
} from '@/Services/api';

/**
 * localStorage key for the most recent extraction payload. Persisting here
 * keeps the dashboard alive across full-page navigations (e.g. the Google
 * OAuth consent round-trip, which reloads the page when it returns to
 * /patient?google=connected). Without this, the patient is forced back to
 * the Upload screen and must re-scan the discharge summary.
 *
 * The key is scoped by `user_id` so account A's restored dashboard can never
 * bleed into account B's session inside the same browser. The single
 * prefix `medguardian_latest_extraction*` is what `clearAllClientState()`
 * matches on logout, so cleanup is still wholesale.
 */
const EXTRACTION_STORAGE_PREFIX = 'medguardian_latest_extraction';

/**
 * Read the current user's id from the persisted session envelope. Returns
 * null on the server, on a missing/corrupt session, or when the user has
 * not yet finalised a login. Single source of truth for "who is currently
 * signed in" at the page level — the API client (`authHeaders()`) uses
 * the same key.
 */
function readCurrentUserId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem('medguardian_session');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { user_id?: unknown };
    if (!parsed || typeof parsed !== 'object') return null;
    const id = parsed.user_id;
    return typeof id === 'string' && id.length > 0 ? id : null;
  } catch {
    return null;
  }
}

/** Build the per-user key for the persisted extraction payload. */
function extractionKey(userId: string): string {
  return `${EXTRACTION_STORAGE_PREFIX}:${userId}`;
}

/** Build the per-user key for the persisted teach-back score. */
function teachBackKey(userId: string): string {
  return `${EXTRACTION_STORAGE_PREFIX}:${userId}:teachback`;
}

/**
 * Read + parse the persisted extraction for the CURRENT user only. Returns
 * null if there is no signed-in user, if no payload is persisted for that
 * user, or if the persisted payload is malformed.
 *
 * The user-id gate is the actual fix for "state bleed between accounts":
 * even if a previous user's row was never cleared (e.g. a logout that
 * happened before `clearAllClientState` was wired up), the new user
 * cannot read it because the key is namespaced by their id.
 */
function loadPersistedExtraction(userId: string | null): UploadResponse | null {
  if (typeof window === 'undefined' || !userId) return null;
  try {
    const raw = window.localStorage.getItem(extractionKey(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as UploadResponse;
    // Defensive shape check — refuse to restore anything that isn't an
    // upload response, so a stale/wrong-version payload can never crash
    // the dashboard.
    if (!parsed || typeof parsed !== 'object' || !parsed.extracted) return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Load the persisted teach-back state for the current user. Returns null
 * when no user is signed in, no score is persisted, or the persisted
 * payload is malformed.
 */
function loadPersistedTeachBack(userId: string | null): TeachBackState | null {
  if (typeof window === 'undefined' || !userId) return null;
  try {
    const raw = window.localStorage.getItem(teachBackKey(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as TeachBackState;
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Patient Portal — the patient's personal care workspace, in human terms.
 *
 * Flow:
 *   Intake (UploadZone)      → upload a discharge summary (14-digit ABHA +
 *                               DPDP consent required).
 *   Safety Check (CriticalAlert + SafetyBanner) → allergy + interaction alerts.
 *   My Care Guide (TeachBackChat + ComprehensionRing) → voice check that the
 *                               patient understands the regimen.
 *   Care Team (ComprehensionRing badge) → care coordinator notified at ≥70%.
 *   Insurance — the TPA dossier is generated on demand in the Admin Console
 *              (app/admin/page.tsx); the patient portal intentionally does not
 *              surface claims/insurance paperwork.
 */
export default function PatientPage() {
  // The patient view runs the real pipeline end-to-end — no demo mode, no
  // cached payloads. Every step hits the live backend.

  // Discharge summary extracted by the Intake step.
  const [extractedData, setExtractedData] = useState<ExtractedData | null>(null);
  // Full shared state from /api/upload (extraction + safety flags).
  const [fullState, setFullState] = useState<UploadResponse | null>(null);
  // Live care-guide state, bubbled up so the comprehension ring + insurance
  // step can read the understanding score.
  const [teachBackState, setTeachBackState] = useState<TeachBackState | null>(null);

  const [isVoiceActive, setIsVoiceActive] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('Tap to start a voice check');

  const teachBackRef = useRef<TeachBackChatHandle | null>(null);

  // Restore the most recent extraction on mount so the dashboard survives
  // full-page navigations (Google OAuth redirect, accidental refresh). The
  // effect runs once; subsequent updates are persisted on every change.
  // The restore is scoped to the signed-in user's id — if a previous
  // account's payload is still in localStorage, the new user can't read it
  // because the key is namespaced by user_id.
  useEffect(() => {
    const userId = readCurrentUserId();
    const restored = loadPersistedExtraction(userId);
    if (restored) {
      setExtractedData(restored.extracted);
      setFullState(restored);
    }
    // Restore the teach-back score independently so the comprehension ring
    // animates immediately on a refresh without re-running the upload.
    const restoredTeachBack = loadPersistedTeachBack(userId);
    if (restoredTeachBack) {
      setTeachBackState(restoredTeachBack);
    } else if (restored?.teach_back) {
      // Fall back to any teach-back embedded in the upload response (older
      // payloads persisted a single combined object).
      setTeachBackState(restored.teach_back);
    }
  }, []);

  // Persist the latest extraction whenever it changes. SSR-safe no-op via
  // the inner typeof guard. We re-read the current user id on every write
  // because the session can be replaced mid-page (account switch) without
  // a remount.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const userId = readCurrentUserId();
    if (!userId) return; // No signed-in user → nothing to persist.
    const key = extractionKey(userId);
    if (fullState) {
      try {
        window.localStorage.setItem(key, JSON.stringify(fullState));
      } catch {
        // Storage quota / disabled — fall back silently; the in-memory
        // state is still correct for the current session.
      }
    } else {
      // Extraction cleared (e.g. user signed out) — drop the persisted copy
      // for this user only so a stale payload can't reappear on the next
      // sign-in. The wholesale logout sweep in clearAllClientState() also
      // covers this key via the prefix match.
      window.localStorage.removeItem(key);
    }
  }, [fullState]);

  // Teach-back score evolves independently of the upload response, so we
  // persist it as a separate slot to keep the two restores independent.
  useEffect(() => {
    if (typeof window === 'undefined' || !teachBackState) return;
    const userId = readCurrentUserId();
    if (!userId) return; // No signed-in user → nothing to persist.
    try {
      window.localStorage.setItem(teachBackKey(userId), JSON.stringify(teachBackState));
    } catch {
      // best-effort
    }
  }, [teachBackState]);

  const handleVoiceToggle = () => {
    teachBackRef.current?.toggleVoice();
  };

  const handleExtracted = (extracted: ExtractedData, full: UploadResponse | null) => {
    setExtractedData(extracted);
    setFullState(full);
    setTeachBackState(full?.teach_back ?? null);
  };

  const handleTeachBackChange = useCallback((state: TeachBackState) => {
    setTeachBackState(state);
  }, []);

  const score = teachBackState?.understanding_score;

  return (
    <div className="min-h-screen bg-[#fafbfc] text-slate-900 antialiased flex flex-col pb-12">
      {/* Patient Portal Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-slate-200 sticky top-0 z-50 px-4 py-3 sm:px-6 sm:py-4">
        <div className="max-w-[1600px] mx-auto flex justify-between items-center gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <Link href="/" className="flex items-center gap-2 min-w-0">
              <span className="h-3 w-3 rounded-full bg-blue-600 animate-pulse shadow-[0_0_10px_rgba(37,99,235,0.6)] shrink-0" />
              <h1 className="text-base sm:text-xl font-semibold tracking-tight text-slate-900 flex items-center gap-2 truncate">
                <HeartPulse className="h-5 w-5 text-blue-600 shrink-0" />
                <span className="truncate">My Care</span>
              </h1>
            </Link>
            <Badge tone="blue" className="hidden sm:inline-flex">Patient Portal</Badge>
          </div>

          <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
            <PWAInstallButton />
            <LogoutButton />
            <Link
              href="/"
              className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-blue-600 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Home</span>
            </Link>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] w-full mx-auto p-4 md:p-6 lg:p-8 space-y-7 flex-1">
        {/* Friendly progress indicator (human labels, no "Agent N") */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Intake', done: !!extractedData, tone: 'bg-blue-500' },
            { label: 'Safety Check', done: !!extractedData, tone: 'bg-emerald-500' },
            { label: 'My Care Guide', done: score != null, tone: 'bg-violet-500' },
            { label: 'Care Team', done: (score ?? 0) >= 70, tone: 'bg-amber-500' },
          ].map((s) => (
            <div
              key={s.label}
              className="flex items-center gap-2.5 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
            >
              <span className={`h-2.5 w-2.5 rounded-full ${s.tone} ${s.done ? '' : 'opacity-30'}`} />
              <span className={`text-sm font-semibold ${s.done ? 'text-slate-900' : 'text-slate-400'}`}>
                {s.label}
              </span>
            </div>
          ))}
        </section>

        {!extractedData ? (
          <ScrollReveal>
            <UploadZone onExtracted={handleExtracted} />
          </ScrollReveal>
        ) : (
          <>
            {/* Safety Check — critical allergy conflict (pulsing rose card). */}
            <ScrollReveal>
              <CriticalAlert safetyFlags={fullState?.safety_flags ?? []} />
            </ScrollReveal>

            {/* Safety Check — drug-interaction flags. */}
            <ScrollReveal>
              <SafetyBanner medications={extractedData.medications} />
            </ScrollReveal>

            {/* Care Guide comprehension — appears once a score is reported. */}
            <ScrollReveal>
              <ComprehensionRing score={score} />
            </ScrollReveal>

            {/* Workspace layout */}
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-7 items-start">
              {/* Left — My Medicines */}
              <div className="xl:col-span-5 space-y-6">
                <ScrollReveal>
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
                    <Activity className="h-3.5 w-3.5 text-blue-500" /> My Medicines
                  </div>
                  <Dashboard extractedData={extractedData} />
                </ScrollReveal>
              </div>

              {/* Right — Voice Care Guide */}
              <div className="xl:col-span-7 space-y-6">
                <ScrollReveal>
                  <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                      <div>
                        <h3 className="text-lg font-semibold tracking-tight text-slate-900 flex items-center gap-2">
                          🎙️ Voice Care Guide
                        </h3>
                        <p className="text-sm text-slate-500 mt-1">{voiceStatus}</p>
                      </div>
                      <button
                        onClick={handleVoiceToggle}
                        disabled={!extractedData}
                        className={`px-5 py-3 rounded-2xl font-semibold text-sm transition-all duration-300 ${
                          isVoiceActive
                            ? 'bg-rose-600 text-white shadow-md shadow-rose-600/20'
                            : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-md shadow-indigo-600/20'
                        }`}
                      >
                        {isVoiceActive ? '🛑 Stop recording' : '🎙️ Start voice check'}
                      </button>
                    </div>
                  </div>
                </ScrollReveal>

                <ScrollReveal>
                  <TeachBackChat
                    ref={teachBackRef}
                    extractedData={extractedData}
                    onVoiceChange={(active, status) => {
                      setIsVoiceActive(active);
                      if (status) setVoiceStatus(status);
                    }}
                    onTeachBackChange={handleTeachBackChange}
                  />
                </ScrollReveal>
              </div>
            </div>

            {/* Medication Reminders — Google Calendar sync + browser notifications.
                Appears only after extraction; uses the real /api/calendar/reminders
                endpoints (Agent 4 adherence, live). */}
            <ScrollReveal>
              <MedicationReminders
                medications={extractedData.medications}
                patientId={fullState?.patient_id}
              />
            </ScrollReveal>
          </>
        )}
      </main>
    </div>
  );
}