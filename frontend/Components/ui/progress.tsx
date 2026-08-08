'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Progress — thin terminal-style bar. `tone` switches the fill colour to
 * match the surrounding telemetry palette; `value` is 0–100.
 */
type ProgressTone = 'blue' | 'emerald' | 'purple' | 'rose' | 'amber';

const fillClasses: Record<ProgressTone, string> = {
  blue: 'bg-blue-500',
  emerald: 'bg-emerald-500',
  purple: 'bg-purple-500',
  rose: 'bg-rose-500',
  amber: 'bg-amber-500',
};

const Progress = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    value?: number;
    tone?: ProgressTone;
  }
>(({ className, value = 0, tone = 'blue', ...props }, ref) => {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div
      ref={ref}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn(
        'relative h-2 w-full overflow-hidden rounded-full bg-slate-800',
        className
      )}
      {...props}
    >
      <div
        className={cn('h-full rounded-full transition-all duration-500', fillClasses[tone])}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
});
Progress.displayName = 'Progress';

export { Progress };
export type { ProgressTone };