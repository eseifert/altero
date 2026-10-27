/// <reference lib="webworker" />
/*
 * The interface's service worker: the app shell, kept so that the installed
 * application opens without a network, and nothing else. See `routes.ts`.
 *
 * Written to `/app/sw.js` by the build, with `__ALTERO_BUILD__` replaced by
 * an id of the build, so that every deploy is a new worker. A new worker
 * waits until the page agrees to reload (`register.ts`), or until every tab
 * of the old one has closed.
 */
import { SHELL, cacheName, route } from './routes'

declare const self: ServiceWorkerGlobalScope
declare const __ALTERO_BUILD__: string

const CACHE = cacheName(__ALTERO_BUILD__)

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name.startsWith('altero-') && name !== CACHE) await caches.delete(name)
      }
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('message', (event) => {
  if (event.data?.type === 'skip-waiting') void self.skipWaiting()
})

self.addEventListener('fetch', (event) => {
  const kind = route(event.request, self.location.origin)
  if (kind === 'asset') event.respondWith(asset(event.request))
  else if (kind === 'shell') event.respondWith(shell(event.request))
})

async function asset(request: Request): Promise<Response> {
  const cache = await caches.open(CACHE)
  const kept = await cache.match(request)
  if (kept) return kept
  const response = await fetch(request)
  if (response.ok) await cache.put(request, response.clone())
  return response
}

async function shell(request: Request): Promise<Response> {
  const cache = await caches.open(CACHE)
  try {
    const response = await fetch(request)
    // The page, not a redirect or a refusal: only that is worth opening offline.
    if (response.ok && !response.redirected && response.headers.get('content-type')?.startsWith('text/html')) {
      await cache.put(SHELL, response.clone())
    }
    return response
  } catch (offline) {
    const kept = await cache.match(SHELL)
    if (kept) return kept
    throw offline
  }
}
