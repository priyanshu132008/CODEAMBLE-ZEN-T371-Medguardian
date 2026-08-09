// frontend/lib/supabaseClient.ts
//
// Browser Supabase client for the "Continue with Google" sign-in flow. Only the
// public anon/publishable key is used — the same RLS-protected key the backend
// exposes as SUPABASE_PUBLISHABLE_KEY — so no secret ever reaches the browser.
//
// The client is a singleton shared by the login page (which starts the OAuth
// flow and stores the PKCE code_verifier in browser storage) and the
// /auth/callback page (which completes the exchange). PKCE requires the
// exchange to happen client-side (the code_verifier lives in localStorage), so
// the callback is a client component — NOT a server route handler.

import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? '';
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? '';

/** True when both public env vars are present. Call sites gate on this before
 *  using `supabase` so a misconfigured deploy shows a clear toast instead of a
 *  cryptic client error. */
export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;