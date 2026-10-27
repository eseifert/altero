/*
 * Registering the service worker, and offering a new version when one waits.
 *
 * In a built interface only: under `npm run dev` there is nothing fingerprinted
 * to keep, and a worker would hand back yesterday's modules.
 */
import { i18n } from '@/i18n'
import { useToastStore } from '@/stores/toasts'

/** `routes.SCOPE`, repeated rather than imported: a module both the page and
 *  the worker import becomes a chunk the worker would have to import, and a
 *  worker script stands alone (`vite.config.ts`). */
const SCOPE = '/app/'

/** How often an open page asks whether a new version has been deployed. */
const CHECK_EVERY = 60 * 60 * 1000

export async function registerServiceWorker(): Promise<void> {
  if (!('serviceWorker' in navigator)) return
  let registration: ServiceWorkerRegistration
  try {
    registration = await navigator.serviceWorker.register(`${SCOPE}sw.js`, { scope: SCOPE })
  } catch {
    // Not installable, and nothing else is lost: the page works without it.
    return
  }

  /* Set when the reader takes the offer. A worker taking control without it
     is the first one installing, and reloading for that is a reload for
     nothing. */
  let asked = false

  // Only a page that already has a worker can be out of date.
  const offer = (waiting: ServiceWorker) => {
    if (!navigator.serviceWorker.controller) return
    useToastStore().show(i18n.global.t('A new version of altero is ready.'), {
      label: i18n.global.t('Reload'),
      run: () => {
        asked = true
        waiting.postMessage({ type: 'skip-waiting' })
      },
    })
  }

  if (registration.waiting) offer(registration.waiting)
  registration.addEventListener('updatefound', () => {
    const installing = registration.installing
    installing?.addEventListener('statechange', () => {
      if (installing.state === 'installed') offer(installing)
    })
  })

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!asked) return
    asked = false
    window.location.reload()
  })

  setInterval(() => void registration.update().catch(() => {}), CHECK_EVERY)
}
