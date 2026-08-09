'use client';

import React, { useCallback, useMemo, useState } from 'react';
import { Bell, Clock, CalendarClock, Loader2, AlertTriangle, RefreshCw, Info, Plug } from 'lucide-react';
import { isAxiosError } from 'axios';
import GoogleCalendarConnection from '@/Components/GoogleCalendarConnection';
import { useBrowserNotifications } from '@/hooks/useBrowserNotifications';
import {
  connectGoogleCalendar,
  disconnectGoogleCalendar,
  getApiErrorMessage,
  getReminders,
  syncReminders,
  type Medication,
  type MedicationSyncOutcome,
  type ReminderMedication,
  type ReminderSyncResponse,
} from '@/Services/api';

/**
 * MedicationReminders — the post-extraction reminder workspace.
 *
 * Appears only after Agent 1 has extracted the medication list. It wires the
 * REAL reminder flow:
 *   1. Google Calendar connection (primary channel — events with popup
 *      reminders that fire independently of this app).
 *   2. A one-click sync that parses each medication into a timed schedule on
 *      the backend and writes Google Calendar events.
 *   3. An opt-in secondary browser-notification layer that fires only while
 *      the portal is open.
 *
 * Honesty rules: backend per-med errors are surfaced verbatim (we never claim a
 * med succeeded when its Google event failed), and the sync calls only the real
 * `/api/calendar/reminders/*` endpoints.
 */
export interface MedicationRemindersProps {
  medications: Medication[];
  patientId?: string;
}

type SyncState = 'idle' | 'syncing' | 'done' | 'error';

function detectTimezone(): string {
  if (typeof window === 'undefined') return 'Asia/Kolkata';
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz || 'Asia/Kolkata';
  } catch {
    return 'Asia/Kolkata';
  }
}

/** Build a Date for the next upcoming occurrence of HH:MM in local time. */
function nextOccurrence(time: string): Date | null {
  const parts = time.split(':');
  const h = Number(parts[0]);
  const m = Number(parts[1]);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
  const now = new Date();
  const candidate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m, 0, 0);
  if (candidate.getTime() <= now.getTime()) return null; // already passed today
  return candidate;
}

export default function MedicationReminders({ medications, patientId }: MedicationRemindersProps) {
  const [connected, setConnected] = useState(false);
  const [syncState, setSyncState] = useState<SyncState>('idle');
  const [syncError, setSyncError] = useState<string | null>(null);
  const [needsReconnect, setNeedsReconnect] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [outcomes, setOutcomes] = useState<MedicationSyncOutcome[] | null>(null);
  const [summary, setSummary] = useState<ReminderSyncResponse | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const notifications = useBrowserNotifications();
  const timezone = useMemo(() => detectTimezone(), []);

  const reminderMeds: ReminderMedication[] = useMemo(
    () =>
      medications.map((m) => ({
        name: m.name,
        dosage: m.dosage,
        frequency: m.frequency,
        duration: m.duration,
      })),
    [medications],
  );

  const handleSync = useCallback(async () => {
    if (syncState === 'syncing' || !connected) return;
    setSyncState('syncing');
    setSyncError(null);
    setNeedsReconnect(false);
    setOutcomes(null);
    setSummary(null);
    try {
      const result = await syncReminders(reminderMeds, timezone, patientId);
      setSummary(result);
      setOutcomes(result.reminders ?? []);
      setSyncState('done');

      // Secondary layer: if browser notifications are granted, schedule the
      // near-term occurrences for TODAY only (while the portal is open). Anything
      // farther out is owned by the Google Calendar layer.
      if (notifications.permission === 'granted') {
        for (const outcome of result.reminders ?? []) {
          if (outcome.status !== 'active') continue;
          for (const slot of outcome.schedule ?? []) {
            const when = nextOccurrence(slot.time);
            if (when) {
              notifications.scheduleReminder(
                `MedGuardian: ${outcome.medication_name}`,
                slot.label ? `Time to take your medicine (${slot.label}).` : 'Time to take your medicine.',
                when,
              );
            }
          }
        }
      }
    } catch (err) {
      // HTTP 401 with the "connection was revoked" detail means the stored
      // refresh token is dead (Google returned 401/403 during refresh).
      // Surface a dedicated reconnect CTA — the small per-med "google:unauthorized"
      // line alone left the patient with no obvious recovery path.
      if (isAxiosError(err) && err.response?.status === 401) {
        setNeedsReconnect(true);
        setConnected(false);
        setSyncError(
          getApiErrorMessage(
            err,
            'Your Google Calendar connection needs to be renewed.',
          ),
        );
      } else {
        setSyncError(getApiErrorMessage(err, 'Could not sync reminders to Google Calendar. Please try again.'));
      }
      setSyncState('error');
    }
  }, [syncState, connected, reminderMeds, timezone, patientId, notifications]);

  // Disconnect the dead connection (best-effort, ignores errors) and start
  // a fresh consent flow. The full-page redirect wipes React state, so we
  // also stash a recovery flag so the patient can re-sync after returning.
  const handleReconnect = useCallback(async () => {
    if (reconnecting) return;
    setReconnecting(true);
    try {
      try {
        await disconnectGoogleCalendar();
      } catch {
        // Best-effort — proceed even if the local row is already gone.
      }
      const url = await connectGoogleCalendar();
      if (typeof url === 'string' && url.trim() !== '') {
        window.location.href = url;
        return;
      }
      setSyncError('Could not start the Google connection. Please try again.');
    } catch (err) {
      setSyncError(getApiErrorMessage(err, 'Could not reconnect Google Calendar.'));
    } finally {
      setReconnecting(false);
    }
  }, [reconnecting]);

  const handleRefreshList = useCallback(async () => {
    setListError(null);
    try {
      const list = await getReminders();
      setOutcomes((prev) => prev); // keep last sync outcomes; the list confirms count
      setSummary((prev) =>
        prev
          ? { ...prev, reminders: prev.reminders, synced: list.count, skipped: prev.skipped, errors: prev.errors }
          : null,
      );
    } catch (err) {
      setListError(getApiErrorMessage(err, 'Could not load saved reminders.'));
    }
  }, []);

  const handleEnableNotifications = useCallback(async () => {
    await notifications.requestPermission();
  }, [notifications]);

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        <CalendarClock className="h-3.5 w-3.5 text-blue-500" /> Medication Reminders
      </div>

      <GoogleCalendarConnection onConnectionChange={setConnected} />

      {/* Reconnect CTA — shown only when a sync fails with HTTP 401
          ("connection revoked / unauthorized"). The patient gets one
          obvious button instead of scanning per-med "google:unauthorized"
          strings for a recovery path. */}
      {needsReconnect && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700">
              <AlertTriangle className="h-5 w-5" />
            </span>
            <div className="flex-1">
              <h3 className="text-base font-semibold text-amber-900">
                Reconnect your Google Calendar
              </h3>
              <p className="mt-1 text-sm text-amber-800 leading-relaxed">
                Google no longer accepts the connection MedGuardian has stored
                (the token may have expired, been revoked, or your account
                security settings changed). Reconnect to sync medication
                reminders — your medicines are safe.
              </p>
              <button
                onClick={handleReconnect}
                disabled={reconnecting}
                className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-amber-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-amber-700 transition-colors disabled:opacity-60"
              >
                {reconnecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plug className="h-4 w-4" />}
                Reconnect Google Calendar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sync action */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-900">Sync {reminderMeds.length} medication{reminderMeds.length === 1 ? '' : 's'} to Google Calendar</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              We turn each medicine&apos;s frequency into timed calendar events with a 10-minute popup reminder.
            </p>
          </div>
          <button
            onClick={handleSync}
            disabled={!connected || syncState === 'syncing'}
            className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {syncState === 'syncing' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />}
            {syncState === 'syncing' ? 'Syncing…' : 'Sync reminders'}
          </button>
        </div>

        {!connected && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-amber-600">
            <Info className="h-3.5 w-3.5" /> Connect Google Calendar above before syncing.
          </p>
        )}

        {syncError && (
          <p className="mt-3 flex items-start gap-1.5 text-xs text-rose-600">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" /> {syncError}
          </p>
        )}

        {syncState === 'done' && summary && (
          <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-3 text-sm">
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-slate-600">
              <span><span className="font-semibold text-emerald-600">{summary.synced}</span> synced</span>
              <span><span className="font-semibold text-slate-500">{summary.skipped}</span> skipped (PRN / review)</span>
              <span><span className="font-semibold text-rose-600">{summary.errors}</span> errors</span>
            </div>
          </div>
        )}
      </div>

      {/* Per-medication outcomes */}
      {outcomes && outcomes.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Your reminder schedule</h3>
          <ul className="space-y-3">
            {outcomes.map((o, i) => (
              <li key={`${o.medication_name}-${i}`} className="rounded-xl border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-2 justify-between">
                  <span className="font-semibold text-sm text-slate-900">{o.medication_name}</span>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {o.status === 'active' && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                        <Clock className="h-3 w-3" /> Active
                      </span>
                    )}
                    {o.status === 'skipped' && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
                        Skipped
                      </span>
                    )}
                    {o.status === 'error' && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-700">
                        <AlertTriangle className="h-3 w-3" /> Error
                      </span>
                    )}
                    {o.recurring ? (
                      <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
                        Recurring
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-semibold text-violet-700">
                        One-time / PRN
                      </span>
                    )}
                    {o.needs_review && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
                        <AlertTriangle className="h-3 w-3" /> Review
                      </span>
                    )}
                  </div>
                </div>

                {o.schedule && o.schedule.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {o.schedule.map((slot, j) => (
                      <span
                        key={`${slot.time}-${j}`}
                        className="inline-flex items-center gap-1 rounded-lg bg-slate-50 border border-slate-200 px-2.5 py-1 text-xs text-slate-600"
                      >
                        <Clock className="h-3 w-3 text-slate-400" />
                        <span className="font-mono font-semibold text-slate-700">{slot.time}</span>
                        {slot.label && <span className="text-slate-400">· {slot.label}</span>}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-slate-500">No fixed schedule (as-needed / one-time).</p>
                )}

                {o.error && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs text-rose-600">
                    <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" /> {o.error}
                  </p>
                )}
              </li>
            ))}
          </ul>

          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={handleRefreshList}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-blue-600 transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Refresh saved reminders
            </button>
            {listError && <span className="text-xs text-rose-600">{listError}</span>}
          </div>
        </div>
      )}

      {/* Secondary layer: browser notifications */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-50 text-violet-600">
              <Bell className="h-5 w-5" />
            </span>
            <div>
              <h3 className="text-base font-semibold text-slate-900">Browser notifications (optional)</h3>
              <p className="text-xs text-slate-500 mt-0.5 max-w-md">
                Browser notifications work while MedGuardian is open. Google Calendar reminders work independently.
              </p>
            </div>
          </div>
          {notifications.supported && notifications.permission !== 'granted' && notifications.permission !== 'unsupported' && (
            <button
              onClick={handleEnableNotifications}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:border-violet-200 hover:text-violet-600 transition-colors"
            >
              <Bell className="h-4 w-4" /> Enable browser notifications
            </button>
          )}
        </div>

        {!notifications.supported && (
          <p className="mt-3 text-xs text-slate-400">Browser notifications are not supported on this device.</p>
        )}
        {notifications.supported && notifications.permission === 'granted' && (
          <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-emerald-700">
            <Bell className="h-3.5 w-3.5" /> Enabled — you&apos;ll get an in-browser alert for any dose coming up while this page is open.
          </p>
        )}
        {notifications.supported && notifications.permission === 'denied' && (
          <p className="mt-3 text-xs text-slate-500">
            You blocked browser notifications. You can re-enable them in your browser site settings.
          </p>
        )}
        {notifications.scheduled.length > 0 && (
          <p className="mt-2 text-[11px] text-slate-400">
            {notifications.scheduled.length} in-browser reminder{notifications.scheduled.length === 1 ? '' : 's'} queued for the next few hours.
          </p>
        )}
      </div>
    </section>
  );
}