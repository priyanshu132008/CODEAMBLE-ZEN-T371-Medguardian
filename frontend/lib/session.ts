// frontend/lib/session.ts
//
// Shared session-finalization helpers used by BOTH the email/password login
// handler (app/login/page.tsx) and the Google OAuth callback
// (app/auth/callback/page.tsx). Centralizing the persistence + RBAC-cookie
// logic here keeps the two auth paths identical so the proxy.ts edge gate sees
// the same cookie contract regardless of how the user authenticated.

import type { AuthRole, AuthSession } from '@/Services/api';

/** Role → portal root, mirroring the proxy.ts role firewall. */
export const PORTALS: Record<AuthRole, string> = {
  patient: '/patient',
  admin: '/admin',
};

export function portalForRole(role: AuthRole): string {
  return PORTALS[role] ?? '/patient';
}

/**
 * Persist the auth session to localStorage and set the two RBAC cookies that
 * `proxy.ts` gates `/patient` and `/admin` on:
 *   - `medguardian_auth=1`  (presence → authenticated)
 *   - `medguardian_role=<role>`  ('patient' | 'admin')
 *
 * Both cookies are SameSite=Lax with a 24h expiry, matching the original login
 * handler. SSR-safe (no-op on the server).
 */
export function persistSession(session: AuthSession): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem('medguardian_session', JSON.stringify(session));
  document.cookie = `medguardian_auth=1; path=/; max-age=86400; SameSite=Lax`;
  document.cookie = `medguardian_role=${session.role}; path=/; max-age=86400; SameSite=Lax`;
}

/**
 * Honour a deep `?redirect` set by the proxy when it bounced an
 * unauthenticated user to /login, but ONLY when the target lies inside the
 * session's own role portal — the RBAC gate would bounce a cross-role redirect
 * anyway, so honouring it here just avoids a visible double-redirect flash.
 * Returns the portal root otherwise. SSR-safe (returns the portal root on the
 * server, where there is no `window`).
 */
export function resolveDeepRedirect(role: AuthRole): string {
  const portal = portalForRole(role);
  if (typeof window === 'undefined') return portal;
  const redirect = new URLSearchParams(window.location.search).get('redirect');
  if (redirect && (redirect === portal || redirect.startsWith(portal + '/'))) {
    return redirect;
  }
  return portal;
}

/**
 * Clear EVERY piece of client-side MedGuardian state we know about. Called
 * by LogoutButton and any other path that needs to sign the user out. The
 * goal is zero state bleed when account A logs out and account B logs in on
 * the same browser.
 *
 * What it clears:
 *   - The persisted `medguardian_session` entry.
 *   - All `medguardian_latest_extraction*` keys (extraction + teach-back,
 *     per-user and global, so a previous user can never reappear).
 *   - The two RBAC cookies that proxy.ts gates /patient and /admin on.
 *   - Any Supabase auth tokens sitting under `sb-*-auth-token` keys (the
 *     Supabase JS client stores its session in localStorage, NOT in
 *     cookies, and `localStorage.removeItem('medguardian_session')` alone
 *     leaves them intact — that's exactly how a "logged out" account can
 *     still appear authenticated to the next supabase.auth.getSession()
 *     call).
 *   - sessionStorage as a whole (defensive — no MedGuardian code stores
 *     anything there today, but a future contributor might).
 *
 * What it deliberately does NOT clear:
 *   - The whole `localStorage` object. Doing so would wipe unrelated keys
 *     a tenant might set (theme preference, other apps on the same origin
 *     in dev). We only delete MedGuardian + Supabase keys.
 *
 * SSR-safe: no-op on the server. Failure mode: any individual delete is
 * wrapped in try/catch so one bad key can't prevent the rest from being
 * cleared.
 */
export function clearAllClientState(): void {
  if (typeof window === 'undefined') return;

  // 1. Drop MedGuardian-specific localStorage keys.
  const keysToRemove: string[] = [];
  for (let i = 0; i < window.localStorage.length; i++) {
    const k = window.localStorage.key(i);
    if (!k) continue;
    if (
      k === 'medguardian_session' ||
      k.startsWith('medguardian_latest_extraction')
    ) {
      keysToRemove.push(k);
    }
  }
  for (const k of keysToRemove) {
    try {
      window.localStorage.removeItem(k);
    } catch {
      /* ignore — quota / disabled storage */
    }
  }

  // 2. Drop Supabase auth tokens (they live under `sb-*-auth-token` in
  //    localStorage). We only remove keys we can see; we never call clear()
  //    on the whole localStorage because that would wipe unrelated tenant data.
  const supabaseKeys: string[] = [];
  for (let i = 0; i < window.localStorage.length; i++) {
    const k = window.localStorage.key(i);
    if (!k) continue;
    // Supabase v2 stores its token under keys like
  //   `sb-<project-ref>-auth-token` (stringified JSON with access_token,
  //   refresh_token, expires_at, …). Match by the prefix and the substring.
    if (k.startsWith('sb-') && k.includes('-auth-token')) {
      supabaseKeys.push(k);
    }
  }
  for (const k of supabaseKeys) {
    try {
      window.localStorage.removeItem(k);
    } catch {
      /* ignore */
    }
  }

  // 3. Drop sessionStorage wholesale (defensive — MedGuardian doesn't
  //    persist anything there today, but if a future feature does, we want
  //    logout to clear it too).
  try {
    window.sessionStorage.clear();
  } catch {
    /* ignore */
  }

  // 4. Expire the two RBAC cookies so the proxy.ts gate bounces the next
  //    request to /login.
  try {
    document.cookie = 'medguardian_auth=; path=/; max-age=0; SameSite=Lax';
    document.cookie = 'medguardian_role=; path=/; max-age=0; SameSite=Lax';
  } catch {
    /* ignore */
  }
}