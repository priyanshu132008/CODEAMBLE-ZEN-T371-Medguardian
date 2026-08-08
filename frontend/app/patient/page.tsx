'use client';

import React, { useCallback, useRef, useState } from 'react';
import Link from 'next/link';
import { HeartPulse, ArrowLeft, Activity } from 'lucide-react';
import SafetyBanner from '@/Components/SafetyBanner';
import Dashboard from '@/Components/Dashboard';
import TeachBackChat from '@/Components/TeachBackChat';
import ScrollReveal from '@/Components/ScrollReveal';
import UploadZone from '@/Components/UploadZone';
import ClaimDossier from '@/Components/ClaimDossier';
import CriticalAlert from '@/Components/CriticalAlert';
import ComprehensionRing from '@/Components/ComprehensionRing';
import LogoutButton from '@/Components/LogoutButton';
import PWAInstallButton from '@/Components/PWAInstallButton';
import { Badge } from '@/Components/ui/badge';

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
 *   Insurance (ClaimDossier) → automatic TPA dossier.
 */
export default function PatientPage() {
  // Live mode — the real pipeline runs. (The demo-mode toggle has been retired
  // from the patient view; the production pipeline is the only path here.)
  const demoMode = false;

  // Discharge summary extracted by the Intake step.
  const [extractedData, setExtractedData] = useState<any>(null);
  // Full shared state from /api/upload (extraction + safety flags).
  const [fullState, setFullState] = useState<any>(null);
  // Live care-guide state, bubbled up so the comprehension ring + insurance
  // step can read the understanding score.
  const [teachBackState, setTeachBackState] = useState<any>(null);

  const [isVoiceActive, setIsVoiceActive] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('Tap to start a voice check');

  const teachBackRef = useRef<any>(null);

  const handleVoiceToggle = () => {
    teachBackRef.current?.toggleVoice();
  };

  const handleExtracted = (extracted: any, full: any) => {
    setExtractedData(extracted);
    setFullState(full);
    setTeachBackState(full?.teach_back ?? null);
  };

  const handleTeachBackChange = useCallback((state: any) => {
    setTeachBackState(state);
  }, []);

  const score = teachBackState?.understanding_score ?? teachBackState?.score;

  return (
    <div className="min-h-screen bg-[#fafbfc] text-slate-900 antialiased flex flex-col pb-12">
      {/* Patient Portal Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-slate-200 sticky top-0 z-50 px-6 py-4">
        <div className="max-w-[1600px] mx-auto flex justify-between items-center gap-4">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-blue-600 animate-pulse shadow-[0_0_10px_rgba(37,99,235,0.6)]" />
              <h1 className="text-xl font-semibold tracking-tight text-slate-900 flex items-center gap-2">
                <HeartPulse className="h-5 w-5 text-blue-600" />
                My Care
              </h1>
            </Link>
            <Badge tone="blue">Patient Portal</Badge>
          </div>

          <div className="flex items-center gap-2">
            <PWAInstallButton />
            <LogoutButton />
            <Link
              href="/"
              className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-blue-600 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Home
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
            <UploadZone onExtracted={handleExtracted} demoMode={demoMode} />
          </ScrollReveal>
        ) : (
          <>
            {/* Safety Check — critical allergy conflict (pulsing rose card). */}
            <ScrollReveal>
              <CriticalAlert safetyFlags={fullState?.safety_flags ?? []} />
            </ScrollReveal>

            {/* Safety Check — drug-interaction flags. */}
            <ScrollReveal>
              <SafetyBanner medications={extractedData.medications} demoMode={demoMode} />
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
                    demoMode={demoMode}
                    onVoiceChange={(active, status) => {
                      setIsVoiceActive(active);
                      if (status) setVoiceStatus(status);
                    }}
                    onTeachBackChange={handleTeachBackChange}
                  />
                </ScrollReveal>
              </div>
            </div>

            {/* Insurance — automatic TPA dossier */}
            <ScrollReveal>
              <ClaimDossier
                extractedData={extractedData}
                safetyFlags={fullState?.safety_flags ?? []}
                teachBackState={teachBackState ?? undefined}
                language={fullState?.language ?? 'en'}
              />
            </ScrollReveal>
          </>
        )}
      </main>
    </div>
  );
}