'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Card — the Deep Navy surface used across the MedGuardian command-center UI.
 *
 * The default variant is the "console" card: a `bg-slate-900` panel with a
 * subtle top telemetry strip, rounded-3xl, and a faint inner border. Variants:
 *   - console  : deep navy panel (default, the workhorse)
 *   - elevated : lighter navy with stronger shadow for focus surfaces
 *   - outline  : transparent panel with a slate border (for inline groupings)
 *   - danger   : navy panel with a rose border for critical surfaces
 *
 * Each Card optionally renders a `telemetry` strip header (the dark terminal
 * bar with a status dot + label + endpoint badge) matching the existing
 * SafetyBanner / UploadZone aesthetic.
 */

type CardVariant = 'console' | 'elevated' | 'outline' | 'danger';
type CardTone = 'blue' | 'emerald' | 'purple' | 'rose';

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    variant?: CardVariant;
    telemetry?: { label: string; badge?: string; tone?: CardTone };
  }
>(({ className, variant = 'console', telemetry, children, ...props }, ref) => {
  const base =
    'rounded-3xl border overflow-hidden shadow-2xl transition-all duration-300';
  const variants: Record<CardVariant, string> = {
    console: 'bg-slate-900 border-white/5 text-white',
    elevated: 'bg-slate-900/95 border-white/10 text-white shadow-[0_8px_40px_rgba(2,6,23,0.45)]',
    outline: 'bg-transparent border-slate-200 text-slate-900 shadow-none',
    danger: 'bg-slate-900 border-rose-500/40 text-white shadow-[0_0_24px_rgba(244,63,94,0.18)]',
  };

  const toneDot: Record<CardTone, string> = {
    blue: 'bg-blue-400 animate-pulse',
    emerald: 'bg-emerald-400 animate-pulse',
    purple: 'bg-purple-400 animate-pulse',
    rose: 'bg-rose-500 animate-ping',
  };
  const toneBadge: Record<CardTone, string> = {
    blue: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
    emerald: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    purple: 'text-purple-400 bg-purple-500/10 border-purple-500/20',
    rose: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
  };

  return (
    <div ref={ref} className={cn(base, variants[variant], className)} {...props}>
      {telemetry && (
        <div className="bg-slate-950/90 px-4 py-2 border-b border-white/5 flex justify-between items-center text-[10px] font-mono tracking-tight text-slate-400">
          <div className="flex items-center gap-2">
            <span className={cn('h-2 w-2 rounded-full', toneDot[telemetry.tone ?? 'blue'])} />
            <span>{telemetry.label}</span>
          </div>
          {telemetry.badge && (
            <span
              className={cn(
                'font-bold uppercase px-2 py-0.5 rounded border',
                toneBadge[telemetry.tone ?? 'blue']
              )}
            >
              {telemetry.badge}
            </span>
          )}
        </div>
      )}
      {children}
    </div>
  );
});
Card.displayName = 'Card';

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-6 flex flex-col gap-1.5', className)} {...props} />
  )
);
CardHeader.displayName = 'CardHeader';

const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn('text-lg font-semibold tracking-tight leading-none', className)}
      {...props}
    />
  )
);
CardTitle.displayName = 'CardTitle';

const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p ref={ref} className={cn('text-sm font-medium text-slate-400', className)} {...props} />
));
CardDescription.displayName = 'CardDescription';

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-6 pt-0', className)} {...props} />
  )
);
CardContent.displayName = 'CardContent';

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-6 pt-0 flex items-center', className)} {...props} />
  )
);
CardFooter.displayName = 'CardFooter';

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter };