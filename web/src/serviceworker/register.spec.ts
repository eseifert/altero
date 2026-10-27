import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useToastStore } from '@/stores/toasts'

import { registerServiceWorker } from './register'

/** A stand-in `navigator.serviceWorker`, holding a worker that waits. */
function serviceWorkers(options: { controlled: boolean }) {
  const waiting = { postMessage: vi.fn() }
  const listeners = new Map<string, () => void>()
  const container = {
    controller: options.controlled ? {} : null,
    register: vi.fn().mockResolvedValue({
      waiting,
      installing: null,
      addEventListener: vi.fn(),
      update: vi.fn().mockResolvedValue(undefined),
    }),
    addEventListener: (name: string, listener: () => void) => listeners.set(name, listener),
  }
  Object.defineProperty(navigator, 'serviceWorker', { value: container, configurable: true })
  return { container, waiting, fire: (name: string) => listeners.get(name)?.() }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  Reflect.deleteProperty(navigator, 'serviceWorker')
})

describe('registering the service worker', () => {
  it('registers the worker for the interface’s scope', async () => {
    const { container } = serviceWorkers({ controlled: false })

    await registerServiceWorker()

    expect(container.register).toHaveBeenCalledWith('/app/sw.js', { scope: '/app/' })
  })

  it('offers a new version that is waiting, and reloads once it is taken', async () => {
    const { waiting, fire } = serviceWorkers({ controlled: true })
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload })

    await registerServiceWorker()
    await flushPromises()
    const [toast] = useToastStore().toasts
    expect(toast.message).toBe('A new version of altero is ready.')

    toast.action!.run()
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: 'skip-waiting' })
    fire('controllerchange')
    expect(reload).toHaveBeenCalledOnce()
  })

  it('offers nothing on the first install, and does not reload for it', async () => {
    const { fire } = serviceWorkers({ controlled: false })
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload })

    await registerServiceWorker()
    fire('controllerchange')

    expect(useToastStore().toasts).toEqual([])
    expect(reload).not.toHaveBeenCalled()
  })
})
