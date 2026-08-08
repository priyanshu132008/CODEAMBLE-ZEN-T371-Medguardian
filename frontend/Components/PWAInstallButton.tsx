'use client';

import { useEffect, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * Dynamic "Install App" button wired to the browser `beforeinstallprompt` event.
 *
 * Browsers don't auto-prompt the PWA install, and Chrome won't even fire the
 * event until the app is installable (manifest + a service worker with a fetch
 * handler — see `PWARegister` / `public/sw.js`). This component captures the
 * deferred prompt the moment the browser offers it, then surfaces a sleek
 * button; clicking it calls `prompt()` to force the native install pop-up.
 *
 * The button renders only when an install prompt is actually available, so on
 * platforms that never fire the event (already installed, iOS Safari which uses
 * manual "Add to Home Screen", or a non-installable context) it stays hidden
 * and leaves surrounding controls untouched.
 */

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export default function PWAInstallButton({ className }: { className?: string }) {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onBeforeInstall = (e: Event) => {
      e.preventDefault(); // hold the prompt for our explicit button
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => setDeferred(null);
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  if (!deferred) return null;

  const onClick = async () => {
    if (!deferred || busy) return;
    setBusy(true);
    try {
      await deferred.prompt();
      await deferred.userChoice;
    } catch {
      /* user dismissed or prompt blocked — no-op */
    } finally {
      setDeferred(null);
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm transition-all duration-200 hover:border-blue-400 hover:text-blue-600 disabled:opacity-60',
        className
      )}
      title="Install MedGuardian as an app"
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
      Install App
    </button>
  );
}