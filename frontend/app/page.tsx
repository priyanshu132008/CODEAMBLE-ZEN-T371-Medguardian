'use client';

import React, { useCallback, useRef, useState } from 'react';
import PresentationSlides from '../Components/PresentationSlides';
import SafetyBanner from '../Components/SafetyBanner';
import Dashboard from '../Components/Dashboard';
import TeachBackChat from '../Components/TeachBackChat';
import ScrollReveal from '../Components/ScrollReveal';
import UploadZone from '../Components/UploadZone';
import ClaimDossier from '../Components/ClaimDossier';

export default function Home() {
  // Default to live API mode — the real Agent 1/2/3 pipeline runs out of the box.
  const [demoMode, setDemoMode] = useState(false);

  // Real Agent 1 OCR output (the `extracted` object from the contract).
  const [extractedData, setExtractedData] = useState<any>(null);
  // Full shared contract state from /api/upload (Agent 1 + 2): patient_id,
  // extracted, safety_flags, teach_back, language. Kept so downstream agents
  // (4 & 5) receive the complete dossier, not just the extracted block.
  const [fullState, setFullState] = useState<any>(null);
  // Live Agent 3 teach-back state, bubbled up from TeachBackChat so the Agent 5
  // claim dossier can include the comprehension score.
  const [teachBackState, setTeachBackState] = useState<any>(null);

  const [isVoiceActive, setIsVoiceActive] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('Click to begin voice streaming');

  // Imperative handle into TeachBackChat so the prominent Voice Stream button
  // drives the same MediaRecorder as the in-chat mic button (one mic, two triggers).
  const teachBackRef = useRef<any>(null);

  const handleVoiceToggle = () => {
    teachBackRef.current?.toggleVoice();
  };

  const handleExtracted = (extracted: any, full: any) => {
    setExtractedData(extracted);
    setFullState(full);
    setTeachBackState(full?.teach_back ?? null);
  };

  // Memoized so TeachBackChat's bubbling effect doesn't loop.
  const handleTeachBackChange = useCallback((state: any) => {
    setTeachBackState(state);
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 antialiased font-sans flex flex-col pb-12">
      {/* Top Application Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-slate-200 sticky top-0 z-50 px-6 py-4 shadow-xs">
        <div className="max-w-[1600px] mx-auto flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-blue-600 animate-pulse shadow-[0_0_10px_rgba(37,99,235,0.6)]" />
              <h1 className="text-xl font-black tracking-tight text-slate-900">MedGuardian Orchestration Portal</h1>
            </div>
            <p className="text-xs font-bold text-slate-500 font-mono mt-0.5">TEAM BYTEFORGE • TRIPLE-AGENT DEMO WORKSPACE</p>
          </div>

          <div className="flex items-center gap-3 bg-slate-100 border border-slate-200 px-3 py-2 rounded-2xl">
            <span className="text-[10px] font-black uppercase text-slate-600 tracking-wider">Demo Mode Switch:</span>
            <button
              onClick={() => setDemoMode(!demoMode)}
              className={`px-3 py-1 rounded-xl text-[11px] font-black transition-all uppercase ${
                demoMode ? 'bg-amber-500 text-white shadow-md' : 'bg-emerald-600 text-white shadow-md'
              }`}
            >
              {demoMode ? '✨ Demo Simulation Active' : '🔌 Live API Production'}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] w-full mx-auto p-4 md:p-6 lg:p-8 space-y-8 flex-1">
        {/* Pitch Deck Block */}
        <PresentationSlides />

        {/* Live System Telemetry Engine Logs */}
        <section className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-[11px]">
          <div className="bg-slate-900 text-slate-300 p-3 rounded-xl border border-blue-500/30 flex items-center justify-between">
            <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-blue-400 animate-pulse"/>AGENT 1: OCR INTAKE LAYER</span>
            <span className="text-blue-400 font-bold px-1.5 bg-blue-500/10 rounded">ENDPOINT: /api/upload</span>
          </div>
          <div className="bg-slate-900 text-slate-300 p-3 rounded-xl border border-emerald-500/30 flex items-center justify-between">
            <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"/>AGENT 2: CONTRAINDICATION ENGINE</span>
            <span className="text-emerald-400 font-bold px-1.5 bg-emerald-500/10 rounded">ENDPOINT: /api/safety-check</span>
          </div>
          <div className="bg-slate-900 text-slate-300 p-3 rounded-xl border border-purple-500/30 flex items-center justify-between">
            <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-purple-400 animate-pulse"/>AGENT 3: VERIFICATION INTERACTION</span>
            <span className="text-purple-400 font-bold px-1.5 bg-purple-500/10 rounded">ENDPOINT: /api/teach-back</span>
          </div>
        </section>

        {!extractedData ? (
          /* AGENT 1 INTAKE — pipeline is hidden until a document is uploaded. */
          <ScrollReveal>
            <UploadZone onExtracted={handleExtracted} demoMode={demoMode} />
          </ScrollReveal>
        ) : (
          <>
            {/* Agent 2 Validation Component */}
            <ScrollReveal>
              <SafetyBanner medications={extractedData.medications} demoMode={demoMode} />
            </ScrollReveal>

            {/* Dynamic Multi-Agent Workspace Layout */}
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">

              {/* Left Block - Dashboard Registry (Agent 1 Output Screen) */}
              <div className="xl:col-span-5 space-y-6">
                <ScrollReveal>
                  <div className="bg-slate-900 text-white rounded-3xl p-4 mb-2 border border-white/5 font-mono text-[10px] tracking-tight flex items-center justify-between">
                    <span>SYSTEM RENDER LAYER: AGENT 1 STRUCTURAL ARRAYS</span>
                    <span className="bg-blue-500 text-white px-2 py-0.5 rounded font-sans uppercase font-bold">Active</span>
                  </div>
                  <Dashboard extractedData={extractedData} />
                </ScrollReveal>
              </div>

              {/* Right Block - Expanded Verification Panel (Agent 3 Chat + Voice Node) */}
              <div className="xl:col-span-7 space-y-6">
                <ScrollReveal>
                  {/* Premium Voice Streaming Node */}
                  <div className="bg-gradient-to-br from-indigo-900 via-slate-900 to-slate-950 border border-indigo-500/30 rounded-3xl p-6 text-white shadow-2xl relative overflow-hidden">
                    <div className="absolute top-0 right-0 bg-indigo-500/10 text-indigo-400 text-[10px] font-mono font-bold uppercase tracking-wider px-3 py-1 rounded-bl-xl border-l border-b border-indigo-500/20">
                      Agent 3 Voice Array Subroute • /api/voice/stt • /api/voice/tts
                    </div>

                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                      <div>
                        <h3 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
                          🎙️ Direct Voice Stream Interface
                        </h3>
                        <p className="text-xs text-slate-300 font-medium mt-1 font-mono">{voiceStatus}</p>
                      </div>

                      <button
                        onClick={handleVoiceToggle}
                        disabled={!extractedData}
                        className={`px-5 py-3 rounded-2xl font-black text-xs uppercase tracking-wider transition-all duration-300 ${
                          isVoiceActive
                            ? 'bg-red-600 animate-pulse text-white shadow-lg shadow-red-600/30 scale-105'
                            : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-md shadow-indigo-600/20'
                        }`}
                      >
                        {isVoiceActive ? '🛑 RECORDING... (Click to stop)' : '🎙️ Open Voice Link'}
                      </button>
                    </div>
                  </div>
                </ScrollReveal>

                {/* Maximized Conversational Engine Area */}
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

            {/* Agent 5 — Hospital Admin Auto-Claim (sits below the Teach-Back
                workspace). Gated on Agent 1 extraction; uses the live teach-back
                score + safety flags in the generated insurance dossier. */}
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