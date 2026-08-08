'use client';

import React, { useState } from 'react';

export default function PresentationSlides() {
  const [activeTab, setActiveTab] = useState<'about' | 'why'>('about');

  return (
    <div className="w-full bg-linear-to-br from-slate-900 via-blue-950 to-indigo-950 text-white rounded-3xl p-6 md:p-8 shadow-2xl relative overflow-hidden border border-blue-500/20">
      {/* Decorative background grid pattern */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-20" />
      
      <div className="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-center border-b border-white/10 pb-4 mb-6 gap-4">
        <div>
          <span className="text-xs font-bold uppercase tracking-widest text-blue-400 bg-blue-500/10 px-3 py-1 rounded-full border border-blue-500/20">
            Pitch Deck Overview
          </span>
          <h2 className="text-2xl font-bold tracking-tight mt-2 bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
            Team ByteForge Core Blueprint
          </h2>
        </div>
        
        {/* Toggle Switch */}
        <div className="flex bg-slate-950 p-1.5 rounded-xl border border-white/5 shadow-inner">
          <button
            onClick={() => setActiveTab('about')}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all duration-300 ${
              activeTab === 'about' ? 'bg-blue-600 text-white shadow-md scale-105' : 'text-slate-400 hover:text-white'
            }`}
          >
            👥 About Our Mission
          </button>
          <button
            onClick={() => setActiveTab('why')}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all duration-300 ${
              activeTab === 'why' ? 'bg-blue-600 text-white shadow-md scale-105' : 'text-slate-400 hover:text-white'
            }`}
          >
            🚀 Why MedGuardian?
          </button>
        </div>
      </div>

      {/* Slide Display Area */}
      <div className="relative min-h-[180px] transition-all duration-500">
        {activeTab === 'about' ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 animate-fadeIn">
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl backdrop-blur-xs">
              <div className="text-2xl mb-2">👁️</div>
              <h4 className="font-bold text-base text-blue-300">Agent 1: Smart OCR Intake</h4>
              <p className="text-xs text-slate-300 mt-1 leading-relaxed">Instantly parses unstructured, chaotic handwritten prescriptions and hospital exit forms into digital medical models using multi-modal AI vision layers.</p>
            </div>
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl backdrop-blur-xs">
              <div className="text-2xl mb-2">🛡️</div>
              <h4 className="font-bold text-base text-emerald-300">Agent 2: Safety Interaction Guard</h4>
              <p className="text-xs text-slate-300 mt-1 leading-relaxed">Cross-references localized medical frameworks and current prescriptions to automatically isolate deadly high-risk contraindications before they occur.</p>
            </div>
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl backdrop-blur-xs">
              <div className="text-2xl mb-2">🗣️</div>
              <h4 className="font-bold text-base text-purple-300">Agent 3: Conversational Verification</h4>
              <p className="text-xs text-slate-300 mt-1 leading-relaxed">Utilizes advanced clinical Teach-Back methods via automated communication protocols, ensuring patient clarity, understanding, and voice synthesis support.</p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-fadeIn">
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl flex gap-4 items-start">
              <span className="bg-red-500/20 text-red-400 p-3 rounded-xl font-bold text-lg">⚠️</span>
              <div>
                <h4 className="font-bold text-base text-white">The Massive Medical Crisis</h4>
                <p className="text-xs text-slate-300 mt-1 leading-relaxed">Over 40% of post-discharge patients experience serious medication non-compliance due to confusing hospital instructions, leading to catastrophic readmission spikes.</p>
              </div>
            </div>
            <div className="bg-white/5 border border-white/10 p-5 rounded-2xl flex gap-4 items-start">
              <span className="bg-emerald-500/20 text-emerald-400 p-3 rounded-xl font-bold text-lg">✨</span>
              <div>
                <h4 className="font-bold text-base text-white">The Autonomous Shield Solution</h4>
                <p className="text-xs text-slate-300 mt-1 leading-relaxed">MedGuardian bridges the clinical loop gaps. By orchestrating three asynchronous specialized LLM agents, we ensure patients are completely safe, monitored, and thoroughly educated.</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}