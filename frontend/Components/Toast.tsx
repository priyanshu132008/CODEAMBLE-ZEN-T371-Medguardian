'use client';

import React, { useCallback, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, XCircle, Info, X } from 'lucide-react';

/**
 * Toast — animated success / error / info alerts used by the Auth Gateway and
 * across MedGuardian. The `useToasts` hook manages the stack and renders the
 * fixed top-right `<Toaster />`; callers just `push({ type, title, message })`.
 */

export type ToastType = 'success' | 'error' | 'info';

export interface ToastItem {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
}

interface ToastConfig {
  icon: typeof CheckCircle2;
  ring: string;
  iconColor: string;
  accent: string;
}

const CONFIG: Record<ToastType, ToastConfig> = {
  success: { icon: CheckCircle2, ring: 'border-emerald-500/40', iconColor: 'text-emerald-400', accent: 'bg-emerald-500/10' },
  error: { icon: XCircle, ring: 'border-rose-500/40', iconColor: 'text-rose-400', accent: 'bg-rose-500/10' },
  info: { icon: Info, ring: 'border-blue-500/40', iconColor: 'text-blue-400', accent: 'bg-blue-500/10' },
};

function ToastCard({ toast, onClose }: { toast: ToastItem; onClose: (id: string) => void }) {
  const cfg = CONFIG[toast.type];
  const Icon = cfg.icon;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 60, scale: 0.9 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 80, scale: 0.85, transition: { duration: 0.2 } }}
      transition={{ type: 'spring', stiffness: 380, damping: 30 }}
      className={`pointer-events-auto flex items-start gap-3 rounded-2xl border ${cfg.ring} bg-slate-900/95 backdrop-blur-xl p-4 shadow-2xl shadow-black/40 min-w-[280px] max-w-sm`}
    >
      <div className={`shrink-0 h-9 w-9 rounded-xl ${cfg.accent} flex items-center justify-center`}>
        <Icon className={`h-5 w-5 ${cfg.iconColor}`} />
      </div>
      <div className="flex-1 pt-0.5">
        <p className="text-sm font-bold text-white tracking-tight">{toast.title}</p>
        {toast.message && <p className="text-xs font-medium text-slate-400 mt-0.5 leading-relaxed">{toast.message}</p>}
      </div>
      <button
        onClick={() => onClose(toast.id)}
        className="shrink-0 text-slate-500 hover:text-white transition-colors"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </motion.div>
  );
}

export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (t: Omit<ToastItem, 'id'>) => {
      // Date.now is fine here — this runs in the browser (client component),
      // not in a Workflow script (where Date.now is sandboxed).
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      setToasts((prev) => [...prev, { ...t, id }]);
      window.setTimeout(() => remove(id), 4500);
    },
    [remove]
  );

  const Toaster = (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-3 pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} onClose={remove} />
        ))}
      </AnimatePresence>
    </div>
  );

  return { push, remove, Toaster };
}