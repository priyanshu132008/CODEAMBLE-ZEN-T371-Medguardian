'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Button — MedGuardian primary interactive surface.
 *
 * Variants map to the Enterprise Command Center palette:
 *   - primary   : vibrant blue (the workhorse CTA)
 *   - navy       : deep-navy filled (secondary emphasis on light surfaces)
 *   - outline    : transparent with slate border (tertiary)
 *   - ghost      : borderless, subtle hover (inline actions)
 *   - danger     : rose (destructive / critical confirm)
 *   - success    : emerald (positive confirm)
 *
 * Sizes: sm / md / lg / icon. The large size is intentionally tall + bold to
 * stay accessible for low-literacy / elderly users (CLAUDE.md constraint).
 */
type ButtonVariant = 'primary' | 'navy' | 'outline' | 'ghost' | 'danger' | 'success';
type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-blue-600 hover:bg-blue-700 text-white shadow-md shadow-blue-600/20',
  navy: 'bg-slate-900 hover:bg-slate-800 text-white border border-white/10 shadow-md shadow-slate-900/30',
  outline: 'bg-transparent border border-slate-300 text-slate-700 hover:bg-slate-100 hover:border-blue-400',
  ghost: 'bg-transparent text-slate-700 hover:bg-slate-100',
  danger: 'bg-rose-600 hover:bg-rose-700 text-white shadow-md shadow-rose-600/20',
  success: 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-md shadow-emerald-600/20',
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'h-9 px-3.5 text-xs rounded-xl',
  md: 'h-11 px-5 text-sm rounded-2xl',
  lg: 'h-14 px-7 text-base rounded-2xl',
  icon: 'h-11 w-11 rounded-2xl',
};

const Button = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    size?: ButtonSize;
  }
>(({ className, variant = 'primary', size = 'md', ...props }, ref) => (
  <button
    ref={ref}
    className={cn(
      'inline-flex items-center justify-center gap-2 font-semibold uppercase tracking-wider transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white',
      variantClasses[variant],
      sizeClasses[size],
      className
    )}
    {...props}
  />
));
Button.displayName = 'Button';

export { Button };
export type { ButtonVariant, ButtonSize };