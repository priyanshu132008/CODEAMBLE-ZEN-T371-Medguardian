'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Badge — small terminal-style status pill used for endpoint tags, severity
 * labels, and compliance markers. Tones mirror the telemetry palette.
 */
type BadgeTone = 'blue' | 'emerald' | 'purple' | 'rose' | 'amber' | 'slate';

const toneClasses: Record<BadgeTone, string> = {
  blue: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  emerald: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  purple: 'text-purple-400 bg-purple-500/10 border-purple-500/20',
  rose: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
  amber: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  slate: 'text-slate-400 bg-slate-500/10 border-slate-500/20',
};

const Badge = React.forwardRef<
  HTMLSpanElement,
  React.HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }
>(({ className, tone = 'slate', ...props }, ref) => (
  <span
    ref={ref}
    className={cn(
      'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider',
      toneClasses[tone],
      className
    )}
    {...props}
  />
));
Badge.displayName = 'Badge';

export { Badge };
export type { BadgeTone };