'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Calendar, CheckCircle2, Loader2, AlertCircle, Link2Off } from 'lucide-react';
import {
  connectGoogleCalendar,
  disconnectGoogleCalendar,
  getCalendarStatus,
  getApiErrorMessage,
  type CalendarStatus,
} from '@/Services/api';

/**
 * GoogleCalendarConnection — manages the patient's Google Calendar link.
 *
 * This is the primary reminder channel: MedGuardian writes timed events (with
 * popup reminders) into the patient's own Google Calendar, which fire
 * independently of this app. Browser notifications are only a secondary,
 * in-session supplement (see useBrowserNotifications).
 *
 * Data load uses a mounted-guard + AbortController so no state is set after the
 * component unmounts and no effect re-runs infinitely. All fetches are fired
 * from explicit user actions or a single mount pass — never from a state
 * change in render.
 */
type ConnectionState = 'loading' | 'connected' | 'disconnected' | 'error';

export interface GoogleCalendarConnectionProps {
  /** Optional callback so a parent can react to connection changes. */
  onConnectionChange?: (connected: boolean) => void;
}

export default function GoogleCalendarConnection({
  onConnectionChange,
}: GoogleCalendarConnectionProps) {
  const [state, setState] = useState<ConnectionState>('loading');
  const [email, setEmail] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);

  // Mounted guard: prevents any setState after unmount (the plan's hard
  // requirement — no state-set-in-effect, no leaky async updates).
  const isMountedRef = useRef(true);
  // Tracks the latest connection value for the change callback without
  // adding it to the effect's dependency list (which would re-run the load).
  const connectedRef = useRef(false);

  const applyStatus = useCallback(
    (status: CalendarStatus) => {
      if (!isMountedRef.current) return;
      const connected = Boolean(status.connected && status.profile);
      connectedRef.current = connected;
      if (connected) {
        setState('connected');
        setEmail(status.profile?.google_account_email ?? null);
        setErrorMsg(null);
      } else {
        setState('disconnected');
        setEmail(null);
      }
      onConnectionChange?.(connected);
    },
    [onConnectionChange],
  );

  // Load the connection status ONCE on mount. The setState calls live inside
  // an async function invoked from the effect, guarded by isMountedRef and
  // an AbortController — never a synchronous setState in the effect body.
  useEffect(() => {
    isMountedRef.current = true;
    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      try {
        const status = await getCalendarStatus();
        if (cancelled || !isMountedRef.current) return;
        applyStatus(status);
      } catch (err) {
        if (cancelled || !isMountedRef.current) return;
        // A failed status check (network/backend) is shown as a retryable
        // error, not a silent "disconnected" — the patient must know the link
        // state is genuinely unknown.
        setState('error');
        setErrorMsg(getApiErrorMessage(err, 'Could not reach MedGuardian to check your Google Calendar link.'));
      }
    };

    void load();

    return () => {
      cancelled = true;
      isMountedRef.current = false;
      controller.abort();
    };
  }, [applyStatus]);

  const handleConnect = useCallback(async () => {
    if (actionPending) return;
    setActionPending(true);
    setErrorMsg(null);
    try {
      const url = await connectGoogleCalendar();
      if (!isMountedRef.current) return;
      // Defensive guard: never navigate to a non-string/empty URL — that
      // would resolve to `localhost:3000/undefined`. connectGoogleCalendar
      // already validates this, but we belt-and-suspenders it here so any
      // future shape change surfaces an error instead of a broken redirect.
      if (typeof url !== 'string' || url.trim() === '') {
        throw new Error('MedGuardian did not return a valid Google connection URL.');
      }
      // Full-page redirect to Google consent. The backend binds the OAuth
      // state to this session; no token is held in the browser.
      if (typeof window !== 'undefined') {
        window.location.href = url;
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      setState('error');
      setErrorMsg(getApiErrorMessage(err, 'Could not start the Google connection. Please try again.'));
      setActionPending(false);
    }
  }, [actionPending]);

  const handleDisconnect = useCallback(async () => {
    if (actionPending) return;
    setActionPending(true);
    setErrorMsg(null);
    try {
      await disconnectGoogleCalendar();
      if (!isMountedRef.current) return;
      connectedRef.current = false;
      setState('disconnected');
      setEmail(null);
      onConnectionChange?.(false);
    } catch (err) {
      if (!isMountedRef.current) return;
      setErrorMsg(getApiErrorMessage(err, 'Could not disconnect Google Calendar. Please try again.'));
    } finally {
      if (isMountedRef.current) setActionPending(false);
    }
  }, [actionPending, onConnectionChange]);

  const handleRetry = useCallback(() => {
    setState('loading');
    setErrorMsg(null);
    // Re-run the mount load by toggling state; the actual fetch is issued
    // from an async function guarded by isMountedRef so it stays safe.
    const reload = async () => {
      try {
        const status = await getCalendarStatus();
        if (!isMountedRef.current) return;
        applyStatus(status);
      } catch (err) {
        if (!isMountedRef.current) return;
        setState('error');
        setErrorMsg(getApiErrorMessage(err, 'Could not reach MedGuardian to check your Google Calendar link.'));
      }
    };
    void reload();
  }, [applyStatus]);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <Calendar className="h-5 w-5" />
          </span>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Google Calendar Reminders</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              The primary channel — reminders fire in your own calendar, even when MedGuardian is closed.
            </p>
          </div>
        </div>

        {state === 'connected' && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
            <CheckCircle2 className="h-3.5 w-3.5" /> Connected
          </span>
        )}
        {state === 'disconnected' && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">
            Not connected
          </span>
        )}
        {state === 'error' && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700">
            <AlertCircle className="h-3.5 w-3.5" /> Error
          </span>
        )}
      </div>

      {/* Status body */}
      {state === 'loading' && (
        <div className="mt-4 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking your Google Calendar link…
        </div>
      )}

      {state === 'connected' && (
        <div className="mt-4">
          <p className="text-sm text-slate-600">
            Linked to <span className="font-medium text-slate-900">{email ?? 'your Google account'}</span>.
            Reminders you sync below will appear as timed events here.
          </p>
          <button
            onClick={handleDisconnect}
            disabled={actionPending}
            className="mt-3 inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:border-rose-200 hover:text-rose-600 transition-colors disabled:opacity-60"
          >
            {actionPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2Off className="h-4 w-4" />}
            Disconnect
          </button>
        </div>
      )}

      {state === 'disconnected' && (
        <div className="mt-4">
          <p className="text-sm text-slate-600">
            Connect your Google Calendar so MedGuardian can write medication reminders as calendar events with popup alerts.
          </p>
          <button
            onClick={handleConnect}
            disabled={actionPending}
            className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 transition-colors disabled:opacity-60"
          >
            {actionPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Calendar className="h-4 w-4" />}
            Connect Google Calendar
          </button>
        </div>
      )}

      {state === 'error' && (
        <div className="mt-4">
          {errorMsg && <p className="text-sm text-rose-600">{errorMsg}</p>}
          <button
            onClick={handleRetry}
            disabled={actionPending}
            className="mt-3 inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:border-blue-200 hover:text-blue-600 transition-colors disabled:opacity-60"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}