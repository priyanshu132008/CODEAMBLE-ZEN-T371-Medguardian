'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldCheck,
  User,
  Building2,
  Lock,
  HeartPulse,
  Stethoscope,
  Loader2,
} from 'lucide-react';
import { Button } from '@/Components/ui/button';
import { Input } from '@/Components/ui/input';
import { Card } from '@/Components/ui/card';
import { useToasts } from '@/Components/Toast';
import { authLogin, authRegister, type AuthRole, type AuthSession } from '@/Services/api';
import { cn } from '@/lib/utils';

/**
 * Auth Gateway — centralised login / register surface for MedGuardian.
 *
 * Wires the existing role-aware shell to the backend auth routes
 * (`/api/auth/login`, `/api/auth/register`) via `Services/api.ts`. On success
 * the session is persisted to localStorage and the user is redirected to the
 * role-appropriate portal:
 *   - patient -> /patient
 *   - admin   -> /admin
 *
 * Animated toasts surface every success / failure state. Until the backend
 * auth routes are implemented, `authLogin`/`authRegister` fall back to a mock
 * session so the demo flow is fully navigable.
 */
type Mode = 'login' | 'register';

const ROLE_CONTEXT: Record<
  AuthRole,
  { icon: typeof User; label: string; sub: string; accent: string; cta: string }
> = {
  patient: {
    icon: User,
    label: 'Patient',
    sub: 'Upload your discharge summary and get guided care at home.',
    accent: 'text-blue-400',
    cta: 'Continue as Patient',
  },
  admin: {
    icon: Building2,
    label: 'Hospital Admin',
    sub: 'Review compliance, safety flags, and auto-generated insurance dossiers.',
    accent: 'text-emerald-400',
    cta: 'Continue as Admin',
  },
};

const DEST: Record<AuthRole, string> = { patient: '/patient', admin: '/admin' };

export default function LoginPage() {
  const router = useRouter();
  const { push, Toaster } = useToasts();

  const [role, setRole] = useState<AuthRole>('patient');
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();

    if (mode === 'register' && password !== confirm) {
      push({ type: 'error', title: 'Passwords do not match', message: 'Please re-enter the same password in both fields.' });
      return;
    }

    setSubmitting(true);
    try {
      const session = mode === 'login'
        ? await authLogin({ email, password, role })
        : await authRegister({ email, password, role, name: email.split('@')[0] });
      finalizeSession(session, mode === 'login' ? 'Signed in' : 'Account created');
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail || err?.response?.data?.message || err?.message || 'Authentication failed.';
      push({
        type: 'error',
        title: 'Authentication failed',
        message: typeof detail === 'string' ? detail : 'Check your credentials and try again.',
      });
      setSubmitting(false);
    }
  };

  // Shared success path: persist session + auth cookie, toast, redirect to the
  // role portal (or a deep ?redirect= target set by the middleware).
  const finalizeSession = (session: AuthSession, title: string) => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('medguardian_session', JSON.stringify(session));
      // Auth cookie the route-protection middleware checks. SameSite=Lax,
      // 24h expiry.
      document.cookie = `medguardian_auth=1; path=/; max-age=86400; SameSite=Lax`;
      document.cookie = `medguardian_role=${session.role}; path=/; max-age=86400; SameSite=Lax`;
    }
    const redirect =
      typeof window !== 'undefined'
        ? new URLSearchParams(window.location.search).get('redirect')
        : null;
    // Only honour a deep redirect that matches this session's role portal —
    // the RBAC proxy would bounce a cross-role redirect anyway, so honouring
    // it here just avoids a visible double-redirect flash.
    const rolePortal = DEST[session.role];
    const redirectValid =
      !!redirect && (redirect === rolePortal || redirect.startsWith(rolePortal + '/'));
    const dest = redirectValid ? redirect! : rolePortal;
    push({
      type: 'success',
      title,
      message: session.mock
        ? `Demo session active — redirecting to ${dest}.`
        : `Welcome, ${session.name}. Redirecting to ${dest}.`,
    });
    setTimeout(() => router.push(dest), 850);
  };

  // Google OAuth — premium "Continue with Google" button. Real OAuth would be
  // delegated to Supabase (supabase.auth.signInWithOAuth({ provider: 'google' }))
  // once the backend provider is configured; until then this simulates a
  // successful Google sign-in for the selected role so the flow is demonstrable.
  const handleGoogle = async () => {
    setSubmitting(true);
    try {
      // TODO: replace with Supabase signInWithOAuth('google') + redirect callback.
      await new Promise((r) => setTimeout(r, 700));
      finalizeSession(
        {
          token: `google.${role}.${Date.now()}`,
          role,
          email: 'you@gmail.com',
          name: 'Google User',
          abha_id: '12341234123412',
          mock: true,
        },
        'Signed in with Google'
      );
    } catch {
      push({ type: 'error', title: 'Google sign-in failed', message: 'Please try again.' });
      setSubmitting(false);
    }
  };

  const ctx = ROLE_CONTEXT[role];
  const RoleIcon = ctx.icon;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 antialiased font-sans flex flex-col items-center justify-center px-4 py-12 relative overflow-hidden">
      {/* Ambient gradient glow */}
      <div className="pointer-events-none absolute -top-32 left-1/2 -translate-x-1/2 h-72 w-[36rem] rounded-full bg-blue-500/15 blur-3xl" />
      <div className="pointer-events-none absolute bottom-0 right-0 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />

      {/* Brand marker */}
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        className="flex items-center gap-2 mb-6 relative z-10"
      >
        <span className="h-3 w-3 rounded-full bg-blue-600 animate-pulse shadow-[0_0_10px_rgba(37,99,235,0.6)]" />
        <h1 className="text-xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
          <HeartPulse className="h-5 w-5 text-blue-600" />
          MedGuardian
        </h1>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45, ease: 'easeOut' }}
        className="w-full max-w-md relative z-10"
      >
        <Card
          variant="console"
          telemetry={{
            label: 'SECURE AUTH GATEWAY • DPDP ACT 2023 COMPLIANT',
            badge: 'TLS ENCRYPTED',
            tone: role === 'admin' ? 'emerald' : 'blue',
          }}
          className="text-white"
        >
          <div className="p-7">
            {/* Role toggle — Patient vs Hospital Admin */}
            <p className="text-[11px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-2">
              Select access tier
            </p>
            <div className="grid grid-cols-2 gap-2 mb-6">
              {(Object.keys(ROLE_CONTEXT) as AuthRole[]).map((r) => {
                const Rc = ROLE_CONTEXT[r];
                const Icon = Rc.icon;
                const active = r === role;
                return (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRole(r)}
                    className={cn(
                      'relative flex flex-col items-center justify-center gap-2 rounded-2xl border px-3 py-4 transition-all duration-300',
                      active
                        ? r === 'admin'
                          ? 'bg-emerald-500/10 border-emerald-500/50 shadow-[0_0_20px_rgba(16,185,129,0.18)]'
                          : 'bg-blue-500/10 border-blue-500/50 shadow-[0_0_20px_rgba(37,99,235,0.18)]'
                        : 'bg-slate-950/60 border-white/5 hover:border-white/15'
                    )}
                  >
                    <Icon className={cn('h-6 w-6', active ? Rc.accent : 'text-slate-500')} />
                    <span className={cn('text-xs font-semibold uppercase tracking-wide', active ? 'text-white' : 'text-slate-500')}>
                      {Rc.label}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Role context line */}
            <div className="flex items-center gap-2 mb-6">
              <RoleIcon className={cn('h-4 w-4 shrink-0', ctx.accent)} />
              <p className="text-sm font-medium text-slate-400">{ctx.sub}</p>
            </div>

            {/* Mode toggle: login / register */}
            <div className="flex items-center gap-1 mb-5 bg-slate-950/60 rounded-xl p-1 border border-white/5">
              {(['login', 'register'] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    'relative flex-1 rounded-lg text-xs font-semibold uppercase tracking-wider py-2 transition-colors',
                    mode === m ? 'text-white' : 'text-slate-500 hover:text-slate-300'
                  )}
                >
                  {mode === m && (
                    <motion.span
                      layoutId="auth-mode-pill"
                      className="absolute inset-0 bg-blue-600 rounded-lg shadow-md shadow-blue-600/30"
                      transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                    />
                  )}
                  <span className="relative z-10">{m === 'login' ? 'Sign In' : 'Register'}</span>
                </button>
              ))}
            </div>

            {/* Google OAuth — premium white/gray button contrasting the navy card.
                STRICT RBAC: admins may ONLY authenticate via email/password, so
                the Google button (and its divider) is hidden entirely when the
                Hospital Admin tab is selected. */}
            {role === 'patient' && (
              <>
                <button
                  type="button"
                  onClick={handleGoogle}
                  disabled={submitting}
                  className="w-full flex items-center justify-center gap-3 rounded-2xl bg-white hover:bg-slate-50 border border-slate-200 text-slate-700 font-semibold text-sm py-3 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
                >
                  <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.56c2.08-1.92 3.28-4.74 3.28-8.09z" />
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.56-2.76c-.98.66-2.23 1.06-3.72 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
                    <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z" />
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84C6.71 7.3 9.14 5.38 12 5.38z" />
                  </svg>
                  Continue with Google
                </button>

                {/* Divider */}
                <div className="flex items-center gap-3 my-1">
                  <div className="h-px flex-1 bg-white/10" />
                  <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500">or with email</span>
                  <div className="h-px flex-1 bg-white/10" />
                </div>
              </>
            )}

            {/* Form */}
            <form onSubmit={handleAuth} className="space-y-3">
              <div>
                <label className="block text-[11px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                  Email
                </label>
                <Input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@hospital.in"
                  className="bg-slate-950/60 border-white/10 text-white placeholder:text-slate-600 focus-visible:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500 pointer-events-none" />
                  <Input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="bg-slate-950/60 border-white/10 text-white placeholder:text-slate-600 focus-visible:border-blue-500 pl-11"
                  />
                </div>
              </div>

              <AnimatePresence mode="wait" initial={false}>
                {mode === 'register' && (
                  <motion.div
                    key="confirm"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.25, ease: 'easeOut' }}
                    className="overflow-hidden"
                  >
                    <label className="block text-[11px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                      Confirm Password
                    </label>
                    <Input
                      type="password"
                      required={mode === 'register'}
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      placeholder="••••••••"
                      className="bg-slate-950/60 border-white/10 text-white placeholder:text-slate-600 focus-visible:border-blue-500"
                    />
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Submit */}
              <Button
                type="submit"
                size="lg"
                variant={role === 'admin' ? 'success' : 'primary'}
                disabled={submitting}
                className="w-full mt-2"
              >
                {submitting ? (
                  <span className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Authenticating…
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    {role === 'admin' ? <Stethoscope className="h-4 w-4" /> : <User className="h-4 w-4" />}
                    {mode === 'login' ? ctx.cta : `Register as ${ctx.label}`}
                  </span>
                )}
              </Button>
            </form>

            {/* Compliance footnote */}
            <div className="mt-6 flex items-center justify-center gap-2 pt-5 border-t border-white/5">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
              <p className="text-[10px] font-mono text-slate-500 tracking-tight">
                Protected under DPDP Act 2023 · ABDM-linked
              </p>
            </div>
          </div>
        </Card>
      </motion.div>

      {/* Back to app */}
      <Link
        href="/"
        className="mt-6 text-xs font-mono font-bold uppercase tracking-wider text-slate-500 hover:text-blue-600 transition-colors relative z-10"
      >
        ← Back to MedGuardian Home
      </Link>

      {Toaster}
    </div>
  );
}