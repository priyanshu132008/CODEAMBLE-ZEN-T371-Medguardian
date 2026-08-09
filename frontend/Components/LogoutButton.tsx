'use client';

import { LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { clearAllClientState } from '@/lib/session';
import { supabase } from '@/lib/supabaseClient';

/**
 * Sleek "Log Out" control for the authenticated portals.
 *
 * State-flush order matters here:
 *   1. Await `supabase.auth.signOut()` — invalidates the Supabase session
 *      server-side AND drops the cached access/refresh tokens in the
 *      Supabase JS client's localStorage entries. If we don't do this, a
 *      subsequent `supabase.auth.getSession()` from the next page would
 *      still see a valid cached session.
 *   2. `clearAllClientState()` — drops every MedGuardian key + the RBAC
 *      cookies the proxy.ts gate reads, plus sessionStorage.
 *   3. `window.location.href = '/'` — HARD navigation, not a router push.
 *      A `router.push` would leave the React tree mounted in memory and
 *      any state-saved-during-render (including the patient page's
 *      `extractedData` React state if it happens to be the active route
 *      when the user clicks logout) would survive in memory and could
 *      re-hydrate on a later visit. A full page load to '/' guarantees
 *      a fresh React tree on the next /patient or /admin navigation.
 *
 * Errors from `signOut()` are swallowed: if Supabase is unreachable, we
 * still want the local state flushed and the user landed on the public
 * landing page rather than stuck mid-handler.
 */
export default function LogoutButton({ className }: { className?: string }) {
  const handleLogout = async () => {
    if (typeof window !== 'undefined') {
      // Best-effort server-side invalidation. If Supabase is down, we still
      // flush local state below — a partially-flushed logout is strictly
      // better than the user being stuck.
      try {
        if (supabase) {
          await supabase.auth.signOut();
        }
      } catch {
        /* ignore — local flush still happens below */
      }
      clearAllClientState();
      // Hard navigation. Same-tab reload to '/' so React state can't
      // re-hydrate on a later visit. Using window.location (not
      // router.push) is intentional.
      window.location.href = '/';
      return;
    }
  };

  return (
    <button
      type="button"
      onClick={handleLogout}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm transition-all duration-200 hover:border-rose-300 hover:text-rose-600',
        className
      )}
      title="Sign out of MedGuardian"
    >
      <LogOut className="h-3.5 w-3.5" />
      Log Out
    </button>
  );
}