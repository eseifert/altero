/*
 * What the service worker does with a request, decided apart from the worker
 * so that it can be tested where there is no worker.
 *
 * Only the application itself is kept: its fingerprinted files, which never
 * change under a name, and the page that names them. Nothing under `/web` and
 * nothing of the v3 API is ever stored. A library kept in a browser would
 * outlive signing out of it on a shared machine, and offline reading is a
 * decision of its own, not a side effect of caching.
 */

/** Where the interface is served, and so what the worker controls. */
export const SCOPE = '/app/'

/** The one key the page is kept under: every route of the app is that page. */
export const SHELL = '/app/'

/**
 * `asset`: from the cache, else the network, and kept.
 * `shell`: from the network, and kept; from the cache only when offline.
 * `pass`: the browser's own business, untouched.
 */
export type Route = 'asset' | 'shell' | 'pass'

export function route(request: { url: string; method: string; mode: string }, origin: string): Route {
  if (request.method !== 'GET') return 'pass'
  const url = new URL(request.url)
  if (url.origin !== origin) return 'pass'
  if (url.pathname.startsWith(`${SCOPE}assets/`)) return 'asset'
  if (request.mode === 'navigate' && (url.pathname === '/app' || url.pathname.startsWith(SCOPE))) {
    return 'shell'
  }
  return 'pass'
}

/** The cache one build keeps; an older build's is deleted when this one takes over. */
export function cacheName(build: string): string {
  return `altero-${build}`
}
