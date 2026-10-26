/**
 * Short messages about something that just happened, with a way to undo it.
 *
 * An errand that changes a library tells the reader it happened, and where it
 * can be taken back, offers to: a toast is quicker than a confirmation asked
 * beforehand and does not stand between the reader and what they meant to do.
 * The trash is still the real undo for deleting; a toast only shortens the way
 * there.
 *
 * A toast goes by itself, but not while the reader is pointing at it or has
 * focus in it (WCAG 2.2.1, timing adjustable) — the clock starts again when
 * they leave.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface ToastAction {
  label: string
  run: () => unknown
}

export interface Toast {
  id: number
  message: string
  action?: ToastAction
}

/** How long a toast stays, long enough to read a sentence and reach a button. */
export const TOAST_DURATION = 6000

/** How many are shown at once; the oldest goes to make room. */
export const MAX_TOASTS = 3

export const useToastStore = defineStore('toasts', () => {
  const toasts = ref<Toast[]>([])
  const timers = new Map<number, ReturnType<typeof setTimeout>>()
  let next = 1

  function dismiss(id: number): void {
    clearTimeout(timers.get(id))
    timers.delete(id)
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  function schedule(id: number): void {
    clearTimeout(timers.get(id))
    timers.set(
      id,
      setTimeout(() => dismiss(id), TOAST_DURATION),
    )
  }

  /** Show a message, and return its id. */
  function show(message: string, action?: ToastAction): number {
    const id = next++
    toasts.value = [...toasts.value, { id, message, action }]
    while (toasts.value.length > MAX_TOASTS) dismiss(toasts.value[0]!.id)
    schedule(id)
    return id
  }

  /** Hold a toast while the reader is at it. */
  function hold(id: number): void {
    clearTimeout(timers.get(id))
    timers.delete(id)
  }

  /** Let it go again, with the whole of its time. */
  function release(id: number): void {
    if (toasts.value.some((toast) => toast.id === id)) schedule(id)
  }

  /** Do what the toast offered, and take it away. */
  async function act(id: number): Promise<void> {
    const toast = toasts.value.find((candidate) => candidate.id === id)
    dismiss(id)
    await toast?.action?.run()
  }

  return { toasts, show, dismiss, hold, release, act }
})
