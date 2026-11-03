import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useToastStore } from '@/stores/toasts'

import { registerServiceWorker } from './register'

class Worker extends EventTarget {
  state = 'installed'
  constructor(readonly build: string) { super() }
  postMessage = vi.fn((message: { type: string }, ports?: { postMessage: (data: unknown) => void }[]) => {
    if (message.type === 'build') ports?.[0]?.postMessage({ build: this.build })
  })
}

function serviceWorkers(options: { controlled?: boolean; waiting?: Worker | null } = {}) {
  const waiting = options.waiting === undefined ? new Worker('next') : options.waiting
  const registration = Object.assign(new EventTarget(), {
    waiting, installing: null as Worker | null,
    update: vi.fn().mockResolvedValue(undefined),
  })
  const container = Object.assign(new EventTarget(), {
    controller: options.controlled === false ? null : new Worker('previous'),
    register: vi.fn().mockResolvedValue(registration),
  })
  Object.defineProperty(navigator, 'serviceWorker', { value: container, configurable: true })
  const install = (worker: Worker) => {
    registration.installing = worker
    registration.dispatchEvent(new Event('updatefound'))
    registration.waiting = worker
    worker.dispatchEvent(new Event('statechange'))
  }
  return { container, registration, waiting, install }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
  document.head.innerHTML = '<meta name="altero-build" content="page">'
  // A synchronous channel facade; the browser checks exercise real ports.
  vi.stubGlobal('MessageChannel', class {
    port1 = { onmessage: null as ((event: { data: unknown }) => void) | null, close: vi.fn() }
    port2 = { postMessage: (data: unknown) => this.port1.onmessage?.({ data }), close: vi.fn() }
  })
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(navigator, 'serviceWorker')
  document.head.innerHTML = ''
})

describe('registering the service worker', () => {
  it('registers the worker for the interface’s scope', async () => {
    const { container } = serviceWorkers({ controlled: false, waiting: null })
    await registerServiceWorker()
    expect(container.register).toHaveBeenCalledWith('/app/sw.js', { scope: '/app/' })
  })

  it('offers a different build and reloads exactly once after accepting it', async () => {
    const { waiting, container } = serviceWorkers()
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload })
    await registerServiceWorker()
    await flushPromises()
    const [toast] = useToastStore().toasts
    expect(toast.message).toBe('A new version of altero is ready.')
    toast.action!.run()
    expect(waiting!.postMessage).toHaveBeenCalledWith({ type: 'skip-waiting' })
    container.controller = waiting
    container.dispatchEvent(new Event('controllerchange'))
    container.dispatchEvent(new Event('controllerchange'))
    expect(reload).toHaveBeenCalledOnce()
  })

  it('activates a waiting build matching a reloaded page without a toast or another reload', async () => {
    const waiting = new Worker('page')
    const { container } = serviceWorkers({ waiting })
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload })
    await registerServiceWorker()
    await flushPromises()
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: 'skip-waiting' })
    container.controller = waiting
    container.dispatchEvent(new Event('controllerchange'))
    await flushPromises()
    expect(useToastStore().toasts).toEqual([])
    expect(reload).not.toHaveBeenCalled()
  })

  it('offers nothing on the first install', async () => {
    const { container, install } = serviceWorkers({ controlled: false, waiting: null })
    await registerServiceWorker()
    const worker = new Worker('page')
    install(worker)
    container.controller = worker
    container.dispatchEvent(new Event('controllerchange'))
    await flushPromises()
    expect(useToastStore().toasts).toEqual([])
  })

  it('offers one notification per build across repeated installation and activation events', async () => {
    const { waiting, container, install } = serviceWorkers()
    await registerServiceWorker()
    install(waiting!)
    install(waiting!)
    await flushPromises()
    expect(useToastStore().toasts).toHaveLength(1)
    container.controller = waiting
    container.dispatchEvent(new Event('controllerchange'))
    await flushPromises()
    expect(useToastStore().toasts).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(6_000)
    install(waiting!)
    await flushPromises()
    expect(useToastStore().toasts).toHaveLength(0)
  })

  it('observes a worker already installing when registration resolves', async () => {
    const { registration } = serviceWorkers({ waiting: null })
    const worker = new Worker('next')
    worker.state = 'installing'
    registration.installing = worker
    await registerServiceWorker()
    worker.state = 'installed'
    registration.waiting = worker
    worker.dispatchEvent(new Event('statechange'))
    await flushPromises()
    expect(useToastStore().toasts).toHaveLength(1)
  })

  it('reloads directly if another tab has already activated the offered build', async () => {
    const { waiting, container, registration } = serviceWorkers()
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload })
    await registerServiceWorker()
    await flushPromises()
    waiting!.state = 'activated'
    registration.waiting = null
    container.controller = waiting
    container.dispatchEvent(new Event('controllerchange'))
    await flushPromises()
    useToastStore().toasts[0]!.action!.run()
    expect(reload).toHaveBeenCalledOnce()
  })

  it('checks for upgrades every five minutes while visible and when returning to the tab', async () => {
    const { registration, install } = serviceWorkers({ waiting: null })
    const listeners = new Map<string, EventListener>()
    vi.spyOn(document, 'addEventListener').mockImplementation((type, listener) => {
      listeners.set(type, listener as EventListener)
    })
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    registration.update.mockImplementation(async () => install(new Worker('next')))
    await registerServiceWorker()
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(registration.update).toHaveBeenCalledOnce()
    expect(useToastStore().toasts).toHaveLength(1)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(registration.update).toHaveBeenCalledOnce()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    listeners.get('visibilitychange')!(new Event('visibilitychange'))
    await flushPromises()
    expect(registration.update).toHaveBeenCalledTimes(2)
    expect(useToastStore().toasts).toHaveLength(0)
  })

  it('does not register duplicate listeners or offers if initialization is called twice', async () => {
    serviceWorkers()
    await Promise.all([registerServiceWorker(), registerServiceWorker()])
    await flushPromises()
    expect(useToastStore().toasts).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(2) // The poll and the toast expiry.
  })

  it('ignores a worker that cannot report its build and an offline update check', async () => {
    const show = vi.spyOn(useToastStore(), 'show')
    const { waiting, registration } = serviceWorkers()
    waiting!.postMessage.mockImplementation(() => {})
    registration.update.mockRejectedValue(new Error('offline'))
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    await registerServiceWorker()
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(show).not.toHaveBeenCalled()
  })
})
