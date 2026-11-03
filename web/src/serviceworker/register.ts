/*
 * Offer an update only when the page's build differs from the incoming worker.
 * A network-first reload may already have fetched the new interface while an
 * old worker still controls it; that page needs no invitation to reload again.
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
const CHECK_EVERY = 5 * 60 * 1000
const registered = new WeakSet<ServiceWorkerRegistration>()

/** A worker may have become redundant, or predate the build message protocol. */
function workerBuild(worker: ServiceWorker): Promise<string | null> {
  return new Promise((resolve) => {
    const channel = new MessageChannel()
    const finish = (build: string | null) => {
      clearTimeout(timeout)
      channel.port1.close()
      channel.port2.close()
      resolve(build)
    }
    const timeout = setTimeout(() => finish(null), 3000)
    channel.port1.onmessage = (event) => finish(typeof event.data?.build === 'string' ? event.data.build : null)
    try {
      worker.postMessage({ type: 'build' }, [channel.port2])
    } catch {
      finish(null)
    }
  })
}

export async function registerServiceWorker(): Promise<void> {
  if (!('serviceWorker' in navigator)) return
  let registration: ServiceWorkerRegistration
  try {
    registration = await navigator.serviceWorker.register(`${SCOPE}sw.js`, { scope: SCOPE })
  } catch {
    // Not installable, and nothing else is lost: the page works without it.
    return
  }
  if (registered.has(registration)) return
  registered.add(registration)
  const pageBuild = document.querySelector<HTMLMetaElement>('meta[name="altero-build"]')?.content
  const offered = new Set<string>()
  let toastId: number | undefined

  // Activation in another tab must not reload this page's unfinished work.
  let asked = false

  const offer = async (worker: ServiceWorker) => {
    const build = await workerBuild(worker)
    if (!pageBuild || !build) return
    if (build === pageBuild) {
      // Already reloaded: take the matching worker without reloading again.
      if (registration.waiting === worker) worker.postMessage({ type: 'skip-waiting' })
      return
    }
    if (offered.has(build)) return
    offered.add(build)
    const toasts = useToastStore()
    if (toastId !== undefined) toasts.dismiss(toastId)
    toastId = toasts.show(i18n.global.t('A new version of altero is ready.'), {
      label: i18n.global.t('Reload'),
      run: () => {
        if (registration.waiting === worker) {
          asked = true
          worker.postMessage({ type: 'skip-waiting' })
        } else window.location.reload()
      },
    })
  }

  if (registration.waiting) void offer(registration.waiting)
  const watched = new WeakSet<ServiceWorker>()
  const observeInstalling = () => {
    const installing = registration.installing
    if (!installing || watched.has(installing)) return
    watched.add(installing)
    const ready = () => {
      if (installing.state === 'installed') void offer(installing)
    }
    installing.addEventListener('statechange', ready)
    ready()
  }
  registration.addEventListener('updatefound', observeInstalling)
  observeInstalling()

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (asked) {
      asked = false
      window.location.reload()
    } else if (navigator.serviceWorker.controller) void offer(navigator.serviceWorker.controller)
  })

  const check = () => {
    if (document.visibilityState === 'visible') void registration.update().catch(() => {})
  }
  setInterval(check, CHECK_EVERY)
  document.addEventListener('visibilitychange', check)
}
