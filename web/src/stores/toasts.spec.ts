import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MAX_TOASTS, TOAST_DURATION, useToastStore } from './toasts'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('toasts', () => {
  it('go by themselves', () => {
    const store = useToastStore()
    store.show('Moved to the trash')

    vi.advanceTimersByTime(TOAST_DURATION - 1)
    expect(store.toasts).toHaveLength(1)

    vi.advanceTimersByTime(1)
    expect(store.toasts).toHaveLength(0)
  })

  it('stay while the reader is at one, and get their whole time back after', () => {
    /* WCAG 2.2.1: a message with a button in it must not leave under the pointer. */
    const store = useToastStore()
    const id = store.show('Moved to the trash')
    vi.advanceTimersByTime(TOAST_DURATION - 100)

    store.hold(id)
    vi.advanceTimersByTime(TOAST_DURATION * 5)
    expect(store.toasts).toHaveLength(1)

    store.release(id)
    vi.advanceTimersByTime(TOAST_DURATION - 1)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(store.toasts).toHaveLength(0)
  })

  it('make room by letting the oldest go', () => {
    const store = useToastStore()
    for (let number = 1; number <= MAX_TOASTS + 1; number += 1) store.show(`Message ${number}`)

    expect(store.toasts.map((toast) => toast.message)).toEqual(['Message 2', 'Message 3', 'Message 4'])
  })

  it('do what they offered once, and leave', async () => {
    const store = useToastStore()
    const run = vi.fn()
    const id = store.show('Moved to the trash', { label: 'Undo', run })

    await store.act(id)
    await store.act(id)

    expect(run).toHaveBeenCalledOnce()
    expect(store.toasts).toHaveLength(0)
  })

  it('do not come back when released after being dismissed', () => {
    const store = useToastStore()
    const id = store.show('Moved to the trash')
    store.hold(id)
    store.dismiss(id)

    store.release(id)
    vi.advanceTimersByTime(TOAST_DURATION)

    expect(store.toasts).toHaveLength(0)
  })
})
