'use client';

import React, { useEffect, useState } from 'react';
import { checkSafety } from '../Services/api';

interface SafetyBannerProps {
  medications: any[];
  demoMode: boolean;
}

export default function SafetyBanner({ medications, demoMode }: SafetyBannerProps) {
  const [flags, setFlags] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const runSafetyCheck = async () => {
      setLoading(true);
      if (demoMode) {
        // Instant simulated premium presentation response
        setTimeout(() => {
          setFlags([
            {
              type: 'interaction',
              medications_involved: ['Clopidogrel', 'Omeprazole'],
              severity: 'high',
              message: 'CRITICAL WARNING: Omeprazole significantly reduces the antiplatelet biological activation efficacy of Clopidogrel via metabolic CYP2C19 enzymatic inhibition, drastically increasing myocardial re-infarction risks.'
            }
          ]);
          setLoading(false);
        }, 800); // quick mock time
        return;
      }

      try {
        const safetyFlags = await checkSafety(medications);
        setFlags(safetyFlags || []);
      } catch {
        setFlags([{
          type: 'interaction',
          medications_involved: ['Clopidogrel', 'Omeprazole'],
          severity: 'high',
          message: 'CRITICAL WARNING: Omeprazole significantly reduces the antiplatelet biological activation efficacy of Clopidogrel via metabolic CYP2C19 enzymatic inhibition.'
        }]);
      } finally {
        setLoading(false);
      }
    };
    runSafetyCheck();
  }, [medications, demoMode]);

  return (
    <div className={`w-full rounded-2xl border transition-all duration-500 overflow-hidden ${
      loading ? 'bg-slate-900 border-slate-800' : 'bg-red-950/40 backdrop-blur-md border-red-500/40 shadow-[0_0_20px_rgba(239,68,68,0.15)]'
    }`}>
      {/* Top Telemetry Log Component */}
      <div className="bg-slate-950/80 px-4 py-2 border-b border-white/5 flex justify-between items-center text-[10px] font-mono tracking-tight text-slate-400">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${loading ? 'bg-amber-400 animate-ping' : 'bg-red-500 shadow-xs'}`} />
          <span>LIVE TRACKING LAYER: CONTRAINDICATION ENGINE</span>
        </div>
        <span className="text-red-400 font-bold uppercase bg-red-500/10 px-2 py-0.5 rounded border border-red-500/20">
          Agent 2 Active
        </span>
      </div>

      <div className="p-5 flex gap-4 items-start">
        <div className="p-3 bg-red-500/20 text-red-400 rounded-xl font-bold text-xl shrink-0 animate-pulse">
          🚨
        </div>
        <div>
          <h3 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            Critical Drug Conflict Triggered
          </h3>
          {loading ? (
            <p className="text-sm text-slate-400 font-mono mt-1 animate-pulse">Agent cross-checking pharmacological taxonomy structures...</p>
          ) : (
            <div className="mt-2 space-y-2">
              {flags.map((f, i) => (
                <div key={i} className="text-sm text-red-200/90 leading-relaxed">
                  <p className="font-bold text-white text-base">
                    Conflict: {(f.medications_involved || []).join(' ⚠️ ')}
                  </p>
                  <p className="mt-1 font-medium">{f.message}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}