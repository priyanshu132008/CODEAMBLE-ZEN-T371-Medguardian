'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * useBrowserNotifications — a SECONDARY, in-browser reminder layer.
 *
 * Browser notifications only fire while the MedGuardian portal is open; they
 * are an opt-in supplement to the primary Google Calendar reminders, which run
 * independently of this app. Permission is requested only on an explicit user
 * action (the "Enable browser notifications" button) — never automatically on
 * mount — and near-term timers are scheduled only for the current session and
 * cleared on unmount so no duplicate or orphan notifications are left behind.
 */

export type NotificationPermissionState =
  | 'granted'
  | 'denied'
  | 'default'
  | 'unsupported';

export interface ScheduledNotification {
  id: string;
  title: string;
  body: string;
  fireAt: number; // epoch ms
}

export interface UseBrowserNotifications {
  supported: boolean;
  permission: NotificationPermissionState;
  requestPermission: () => Promise<NotificationPermissionState>;
  scheduleReminder: (title: string, body: string, fireAt: Date) => string | null;
  clearReminder: (id: string) => void;
  scheduled: ScheduledNotification[];
}

// Only schedule notifications that fall within this window while the portal is
// open. Anything farther out belongs to the Google Calendar layer.
const MAX_SCHEDULE_AHEAD_MS = 1000 * 60 * 60 * 8; // 8 hours

function readInitialPermission(): NotificationPermissionState {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
  return (Notification.permission as NotificationPermissionState) || 'default';
}

function readInitialSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window;
}

export function useBrowserNotifications(): UseBrowserNotifications {
  // Lazy initializers read the browser Notification API once during the first
  // client render (no permission prompt — a passive read). This avoids any
  // setState-in-effect: the only mount effect below is a timer cleanup that
  // contains no setState call.
  const [supported] = useState<boolean>(readInitialSupported);
  const [permission, setPermission] = useState<NotificationPermissionState>(readInitialPermission);
  const [scheduled, setScheduled] = useState<ScheduledNotification[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // Clear every outstanding timer on unmount so no notification fires after the
  // portal closes (and no duplicate timer is ever left running). This effect
  // only returns a cleanup — it never calls setState in its body.
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    };
  }, []);

  const requestPermission = useCallback(async (): Promise<NotificationPermissionState> => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      setPermission('unsupported');
      return 'unsupported';
    }
    try {
      const result = await Notification.requestPermission();
      const next = (result || 'denied') as NotificationPermissionState;
      setPermission(next);
      return next;
    } catch {
      setPermission('denied');
      return 'denied';
    }
  }, []);

  const clearReminder = useCallback((id: string) => {
    const timers = timersRef.current;
    const t = timers.get(id);
    if (t) {
      clearTimeout(t);
      timers.delete(id);
    }
    setScheduled((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const scheduleReminder = useCallback(
    (title: string, body: string, fireAt: Date): string | null => {
      if (!supported || permission !== 'granted') return null;
      const now = Date.now();
      const fireAtMs = fireAt.getTime();
      if (fireAtMs <= now) return null; // already past — do not fire stale
      if (fireAtMs - now > MAX_SCHEDULE_AHEAD_MS) return null; // too far — leave to Google

      const id = `${now}-${Math.round(fireAtMs)}`;
      const delay = fireAtMs - now;

      const timer = setTimeout(() => {
        try {
          if (typeof window !== 'undefined' && 'Notification' in window) {
            new Notification(title, { body });
          }
        } catch {
          // Notification construction can throw in some browsers; swallow.
        }
        // Remove from the scheduled list once fired.
        timersRef.current.delete(id);
        setScheduled((prev) => prev.filter((n) => n.id !== id));
      }, delay);

      timersRef.current.set(id, timer);
      setScheduled((prev) => [
        ...prev,
        { id, title, body, fireAt: fireAtMs },
      ]);
      return id;
    },
    [supported, permission],
  );

  return {
    supported,
    permission,
    requestPermission,
    scheduleReminder,
    clearReminder,
    scheduled,
  };
}