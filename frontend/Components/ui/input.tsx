'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Input — accessible text field for the MedGuardian forms (ABHA ID, login,
 * search). Larger hit area + bold placeholder weight for low-literacy /
 * elderly accessibility (CLAUDE.md constraint). Tracks a `mono` prop so
 * structured identifiers (14-digit ABHA, codes) render in JetBrains Mono.
 */
const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { mono?: boolean }
>(({ className, mono, type = 'text', ...props }, ref) => (
  <input
    ref={ref}
    type={type}
    className={cn(
      'flex h-12 w-full rounded-2xl border border-slate-300 bg-white px-4 py-2 text-base font-medium text-slate-900 placeholder:font-medium placeholder:text-slate-400 transition-all duration-200',
      'focus-visible:outline-none focus-visible:border-blue-500 focus-visible:ring-2 focus-visible:ring-blue-500/30',
      'disabled:cursor-not-allowed disabled:opacity-50',
      mono && 'font-jetbrains tracking-wider',
      className
    )}
    {...props}
  />
));
Input.displayName = 'Input';

export { Input };