'use client';

import { useEffect } from 'react';

/**
 * Registers the MedGuardian service worker (`/sw.js`) so the app meets
 * Chrome's PWA installability criteria — a controlled fetch handler is what
 * makes `beforeinstallprompt` fire, which the "Install App" button depends on.
 *
 * Renders nothing; a pure side-effect component mounted once in the root
 * layout. Failures are swallowed (an unsupported/private browser simply
 * stays an ordinary web page).
 */
export default function PWARegister() {
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!('serviceWorker' in navigator)) return;

    const register = () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {
        /* unsupported / blocked — silently fall back to non-installable web app */
      });
    };

    if (document.readyState === 'complete') register();
    else window.addEventListener('load', register, { once: true });
  }, []);

  return null;
}