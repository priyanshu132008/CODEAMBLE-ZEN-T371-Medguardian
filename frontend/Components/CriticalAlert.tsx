'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { ShieldAlert, Siren } from 'lucide-react';
import { Badge } from '@/Components/ui/badge';
import type { AllergyConflictSafetyFlag, SafetyFlag } from '../Services/api';

/**
 * CriticalAlert — Agent 2 allergy-conflict surface.
 *
 * Renders ONLY `allergy_conflict` flags (e.g. Amoxicillin prescribed despite a
 * documented Penicillin allergy) emitted by the safety engine. These are
 * distinct from the generic drug-drug `interaction` flags that SafetyBanner
 * already shows — this component is the dedicated, eye-catching CRITICAL
 * surface for allergy conflicts.
 *
 * Aesthetic: bold, pulsing `border-rose-500` card with red text against the
 * deep navy background — designed to be impossible to miss.
 *
 * Flag shape (from backend agents/safety_check.py):
 *   { type: "allergy_conflict", severity: "CRITICAL",
 *     message: "...", medication: "...", allergy: "..." }
 *
 * Pass the FULL `safety_flags` array (from `fullState.safety_flags`); this
 * component filters internally and renders nothing if there are no allergy
 * conflicts — so it is always safe to mount.
 */
interface CriticalAlertProps {
  safetyFlags?: SafetyFlag[];
}

export default function CriticalAlert({ safetyFlags }: CriticalAlertProps) {
  const allergyConflicts = (safetyFlags || []).filter(
    (f): f is AllergyConflictSafetyFlag => f?.type === 'allergy_conflict',
  );

  if (allergyConflicts.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className="w-full rounded-3xl border-2 border-rose-500 bg-slate-900 shadow-[0_0_30px_rgba(244,63,94,0.35)] animate-pulse overflow-hidden"
    >
      {/* Terminal telemetry strip */}
      <div className="bg-slate-950/90 px-4 py-2 border-b border-rose-500/30 flex justify-between items-center text-[10px] font-mono tracking-tight text-rose-300">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-rose-500 animate-ping" />
          <span>AGENT 2 · ALLERGY CROSS-REFERENCE ENGINE</span>
        </div>
        <Badge tone="rose">CRITICAL · 403-LEVEL CONFLICT</Badge>
      </div>

      <div className="p-5 md:p-6">
        <div className="flex items-start gap-4">
          {/* Pulsing siren icon */}
          <div className="relative shrink-0">
            <span className="absolute inset-0 rounded-2xl bg-rose-500/30 animate-ping" />
            <div className="relative h-12 w-12 rounded-2xl bg-rose-500/20 border border-rose-500/50 flex items-center justify-center">
              <ShieldAlert className="h-7 w-7 text-rose-400" strokeWidth={2.2} />
            </div>
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Siren className="h-4 w-4 text-rose-400 shrink-0" />
              <h3 className="text-lg md:text-xl font-bold tracking-tight text-rose-100 uppercase">
                Allergy Conflict Detected
              </h3>
            </div>
            <p className="text-sm font-medium text-rose-300/80 mt-1">
              A prescribed medication directly conflicts with a documented patient
              allergy. Do not administer without physician review.
            </p>

            {/* One conflict row per (medication, allergy) pair */}
            <div className="mt-4 space-y-3">
              {allergyConflicts.map((f, i) => (
                <div
                  key={`${f.medication}-${f.allergy}-${i}`}
                  className="rounded-2xl border border-rose-500/40 bg-rose-950/30 p-4"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
                    <span className="font-jetbrains text-base font-bold text-white">
                      {f.medication || 'Unknown medication'}
                    </span>
                    <span className="text-rose-400 font-bold text-lg">⚠ VS ⚠</span>
                    <span className="font-jetbrains text-base font-bold text-rose-300">
                      {f.allergy || 'Unknown allergy'}
                    </span>
                  </div>
                  {f.message && (
                    <p className="text-sm text-rose-200/90 font-medium leading-relaxed mt-2">
                      {f.message}
                    </p>
                  )}
                  {f.severity && (
                    <div className="mt-3">
                      <Badge tone="rose">{String(f.severity)} SEVERITY</Badge>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}