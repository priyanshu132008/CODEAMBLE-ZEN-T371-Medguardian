/* MedGuardian service worker.
 *
 * Minimal network-first fetch handler. A controlled fetch handler is required
 * for Chrome to consider the app installable (and therefore fire
 * `beforeinstallprompt`, which the "Install App" button relies on). We keep
 * caching light — a network-first strategy with an offline cache fallback — so
 * the hackathon demo never serves stale app shells while still meeting the
 * installability criteria.
 */
const CACHE = 'medguardian-v1';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  event.respondWith(
    (async () => {
      try {
        const response = await fetch(request);
        // Cache successful same-origin GETs for offline resilience.
        if (response.ok && new URL(request.url).origin === self.location.origin) {
          const copy = response.clone();
          caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
        }
        return response;
      } catch {
        const cached = await caches.match(request);
        return cached || (await caches.match('/')) || Response.error();
      }
    })()
  );
});