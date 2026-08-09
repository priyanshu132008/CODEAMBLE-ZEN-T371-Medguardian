'use client';

// app/auth/callback/page.tsx
//
// Google OAuth PKCE callback. This route is intentionally OUTSIDE the proxy.ts
// matcher (which only gates /patient and /admin), so the OAuth `?code=` is not
// dropped by the RBAC edge gate before it can be exchanged.
//
// Flow:
//   1. The login page calls supabase.auth.signInWithOAuth({ provider:'google',
//      options:{ redirectTo: '/auth/callback' } }) and navigates the browser to
//      Google's consent page. The PKCE code_verifier is stored in browser
//      localStorage by the same singleton client.
//   2. Google redirects back to /auth/callback?code=... .
//   3. Here we exchange the code for a Supabase session (client-side — the
//      code_verifier lives in browser storage, so this MUST be a client
//      component, not a server route handler).
//   4. We send the resulting Supabase access token to the backend
//      /api/auth/me, which validates it and returns the SERVER-RESOLVED role
//      (admin from ADMIN_EMAILS). The frontend never decides admin status.
//   5. We persist the session (localStorage + RBAC cookies — identical to the
//      email/password login) and push to the role portal.
//
// No Google OAuth access/refresh token (the Calendar one) is ever handled here;
// this is Supabase Auth's Google login, whose session JWT is the same token the
// email/password flow already stores. Calendar connection happens later,
// server-side, inside the patient portal.

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, AlertCircle } from 'lucide-react';
import { supabase } from '@/lib/supabaseClient';
import { getMe, getApiErrorMessage, type AuthSession } from '@/Services/api';
import { persistSession, portalForRole } from '@/lib/session';

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  // Guard against React StrictMode's double-invoked effects so the exchange +
  // /me call fire exactly once.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    let cancelled = false;

    (async () => {
      try {
        if (!supabase) {
          throw new Error(
            'Supabase is not configured on the frontend. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.',
          );
        }

        // Complete the PKCE exchange. The code_verifier is in browser storage
        // (set by signInWithOAuth on the login page), so the client — not the
        // server — must perform the exchange.
        const code = new URLSearchParams(window.location.search).get('code');
        if (code) {
          const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
          if (exchangeError) throw exchangeError;
        }

        const { data, error: sessionError } = await supabase.auth.getSession();
        if (sessionError) throw sessionError;
        const session = data.session;
        if (!session) throw new Error('No session returned after Google sign-in.');
        const accessToken = session.access_token;

        // Validate the token with our backend and obtain the SERVER-RESOLVED
        // role. The frontend never decides admin status — /me returns "admin"
        // only when the validated email is on ADMIN_EMAILS.
        const me = await getMe(accessToken);

        if (cancelled) return;

        const authSession: AuthSession = {
          token: accessToken,
          role: me.role,
          email: me.email,
          name: me.name,
          mock: false,
        };
        persistSession(authSession);
        router.replace(portalForRole(me.role));
      } catch (err) {
        if (cancelled) return;
        setError(getApiErrorMessage(err, 'Google sign-in did not complete.'));
        // Give the user a moment to read the error, then return to login so
        // they can retry with email/password.
        setTimeout(() => router.replace('/login'), 2500);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4 text-slate-900">
      {error ? (
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <AlertCircle className="h-8 w-8 text-red-500" />
          <p className="text-sm font-semibold text-red-600">{error}</p>
          <p className="text-xs text-slate-500">Redirecting to sign in…</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 text-center">
          <Loader2 className="h-7 w-7 animate-spin text-blue-600" />
          <p className="text-sm font-semibold text-slate-700">Finishing Google sign-in…</p>
        </div>
      )}
    </div>
  );
}