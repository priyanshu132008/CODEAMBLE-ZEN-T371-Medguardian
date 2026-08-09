'use client';

import React, { useEffect, useState } from 'react';
import { ShieldCheck, AlertTriangle, Loader2 } from 'lucide-react';
import {
  checkSafety,
  getApiErrorMessage,
  type InteractionSafetyFlag,
  type Medication,
  type SafetyFlag,
} from '../Services/api';

/**
 * SafetyBanner — Agent 2 drug-interaction / duplicate / dosage-anomaly surface.
 *
 * Calls the REAL `/api/safety-check` endpoint and renders whatever the rule-based
 * safety engine returns. It deliberately renders ONLY the non-allergy flags
 * (`interaction` / `duplicate` / `dosage_anomaly`); the `allergy_conflict`
 * (CRITICAL) flags are owned by the dedicated `CriticalAlert` component, so the
 * two never duplicate the same alert.
 *
 * Live + honest failure handling — no fabricated data, ever:
 *   loading  → a neutral "checking your medicines…" state.
 *   error    → an honest "safety check unavailable" banner with the backend's
 *              message. A backend outage must NEVER be presented as a fake
 *              critical drug conflict (that would be a dangerous lie to a patient).
 *   no flags → a reassuring "no interactions found" state.
 *   flags    → the real flags the engine returned.
 */
interface SafetyBannerProps {
  medications: Medication[];
}

const NON_ALLERGY = new Set<SafetyFlag['type']>([
  'interaction',
  'duplicate',
  'dosage_anomaly',
]);

function isInteractionFlag(f: SafetyFlag): f is InteractionSafetyFlag {
  return NON_ALLERGY.has(f.type);
}

export default function SafetyBanner({ medications }: SafetyBannerProps) {
  const [flags, setFlags] = useState<InteractionSafetyFlag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const runSafetyCheck = async () => {
      setLoading(true);
      setError(null);
      try {
        const safetyFlags = await checkSafety(medications);
        if (!cancelled) {
          setFlags((safetyFlags || []).filter(isInteractionFlag));
        }
      } catch (err) {
        // Honest failure: never fabricate a safety flag. Surface the backend
        // error so the patient knows the check did not run — a fake "critical
        // drug conflict" on a network blip would be a dangerous false alarm.
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to run the safety check.'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    runSafetyCheck();
    return () => {
      cancelled = true;
    };
  }, [medications]);

  if (loading) {
    return (
      <div className="w-full rounded-2xl border border-slate-200 bg-white p-5 flex items-center gap-3 shadow-sm">
        <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
        <p className="text-sm font-medium text-slate-500">
          Checking your medicines for interactions…
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full rounded-2xl border border-amber-200 bg-amber-50 p-5 flex gap-3 items-start shadow-sm">
        <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-amber-900">Safety check unavailable</p>
          <p className="text-xs text-amber-800/80 mt-0.5">{error}</p>
          <p className="text-[11px] text-amber-700/70 mt-1">
            Ensure the backend is running so the drug-interaction check can complete.
          </p>
        </div>
      </div>
    );
  }

  if (flags.length === 0) {
    return (
      <div className="w-full rounded-2xl border border-emerald-200 bg-emerald-50 p-5 flex gap-3 items-center shadow-sm">
        <ShieldCheck className="h-5 w-5 text-emerald-600 shrink-0" />
        <p className="text-sm font-semibold text-emerald-800">
          No drug interactions or duplicates found in your current medication list.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full rounded-2xl border border-rose-300 bg-rose-50 shadow-sm overflow-hidden">
      <div className="bg-rose-100/70 px-4 py-2 border-b border-rose-200 flex items-center gap-2 text-[10px] font-mono tracking-tight text-rose-700">
        <AlertTriangle className="h-3.5 w-3.5" />
        <span className="font-bold uppercase">Safety Check · {flags.length} flag{flags.length > 1 ? 's' : ''}</span>
      </div>
      <div className="p-5 space-y-3">
        {flags.map((f, i) => (
          <div key={i} className="rounded-xl border border-rose-200 bg-white p-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-rose-100 text-rose-700">
                {f.type.replace('_', ' ')}
              </span>
              {f.severity && (
                <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-rose-600 text-white">
                  {f.severity}
                </span>
              )}
            </div>
            {f.medications_involved && f.medications_involved.length > 0 && (
              <p className="mt-2 text-sm font-bold text-rose-900">
                {f.medications_involved.join('  ⚠  ')}
              </p>
            )}
            {f.message && (
              <p className="mt-1 text-sm text-rose-800/90 font-medium leading-relaxed">{f.message}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}