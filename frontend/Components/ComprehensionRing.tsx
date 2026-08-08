'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Radio, ShieldCheck } from 'lucide-react';

/**
 * ComprehensionRing — Agent 3 teach-back comprehension gauge + Agent 4
 * care-coordination auto-trigger indicator.
 *
 * Renders a circular SVG progress ring whose colour shifts with the live
 * understanding score (rose < 50, amber 50–69, emerald ≥ 70). When the score
 * crosses the 70% handoff threshold, a pulsing "Agent 4 Care Coordinator
 * auto-triggered" badge appears — the backend's /api/coordinator/trigger fires
 * automatically from the teach-back route once comprehension ≥ 70%.
 *
 * Renders nothing until a score has been reported (score === undefined), so it
 * is always safe to mount in the patient portal.
 */
interface ComprehensionRingProps {
  score?: number;
}

export default function ComprehensionRing({ score }: ComprehensionRingProps) {
  if (score == null) return null;

  const RADIUS = 52;
  const CIRC = 2 * Math.PI * RADIUS;
  const pct = Math.max(0, Math.min(100, score));
  const offset = CIRC - (pct / 100) * CIRC;

  const tone =
    pct >= 70
      ? { stroke: '#34d399', glow: 'rgba(52,211,153,0.45)', text: 'text-emerald-300', label: 'Comprehension Verified' }
      : pct >= 50
        ? { stroke: '#fbbf24', glow: 'rgba(251,191,36,0.4)', text: 'text-amber-300', label: 'Partial Comprehension' }
        : { stroke: '#fb7185', glow: 'rgba(251,113,133,0.4)', text: 'text-rose-300', label: 'Needs Reinforcement' };

  const triggered = pct >= 70;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
      className="rounded-3xl border border-white/5 bg-gradient-to-br from-slate-900 to-slate-950 p-6 shadow-2xl"
    >
      <div className="flex flex-col sm:flex-row items-center gap-6">
        {/* Circular progress ring */}
        <div className="relative shrink-0" style={{ filter: `drop-shadow(0 0 12px ${tone.glow})` }}>
          <svg width="140" height="140" viewBox="0 0 140 140" className="-rotate-90">
            <circle cx="70" cy="70" r={RADIUS} fill="none" stroke="rgba(148,163,184,0.12)" strokeWidth="10" />
            <motion.circle
              cx="70"
              cy="70"
              r={RADIUS}
              fill="none"
              stroke={tone.stroke}
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={CIRC}
              initial={{ strokeDashoffset: CIRC }}
              animate={{ strokeDashoffset: offset }}
              transition={{ duration: 0.9, ease: 'easeOut' }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={`font-jetbrains text-3xl font-bold ${tone.text}`}>{Math.round(pct)}%</span>
            <span className="text-[9px] font-mono uppercase tracking-wider text-slate-500 mt-0.5">Score</span>
          </div>
        </div>

        {/* Status + Agent 4 trigger */}
        <div className="flex-1 text-center sm:text-left">
          <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-1">
            My Care Guide · Comprehension
          </p>
          <p className={`text-lg font-bold tracking-tight ${tone.text}`}>{tone.label}</p>
          <p className="text-xs font-medium text-slate-400 mt-1.5 leading-relaxed">
            {triggered
              ? 'Comprehension threshold cleared. Care coordinator notified.'
              : 'Patient must reach 70% to auto-trigger care coordination handoff.'}
          </p>

          {/* Agent 4 auto-trigger badge */}
          <motion.div
            initial={false}
            animate={triggered ? { opacity: 1, y: 0 } : { opacity: 0, y: 8, height: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden mt-3"
          >
            {triggered && (
              <div className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 shadow-[0_0_20px_rgba(52,211,153,0.25)]">
                <motion.span
                  animate={{ scale: [1, 1.15, 1] }}
                  transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut' }}
                >
                  <Radio className="h-4 w-4 text-emerald-400" />
                </motion.span>
                <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-emerald-300">
                  Care team notified · comprehension ≥ 70%
                </span>
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-400/70" />
              </div>
            )}
          </motion.div>
        </div>
      </div>
    </motion.div>
  );
}