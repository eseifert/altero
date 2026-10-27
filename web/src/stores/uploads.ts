/**
 * Files on their way to the server, and how far each has got.
 *
 * Kept apart from the library because an upload outlives what is on screen: a
 * file dropped on a collection is still going after the reader has opened
 * another, and the panel saying so belongs to the page rather than to a pane.
 * One that finishes leaves the list; one that fails stays, saying why, until it
 * is dismissed -- a failure that vanished on its own would be one nobody saw.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { isCancelled } from '@/api/client'

export interface Upload {
  id: number
  /** The file's name, as the reader knows it. */
  name: string
  sent: number
  total: number
  /** Why it failed, once it has. */
  error: string | null
}

export const useUploadStore = defineStore('uploads', () => {
  const uploads = ref<Upload[]>([])
  const controllers = new Map<number, AbortController>()
  let next = 1

  function update(id: number, changes: Partial<Upload>): void {
    uploads.value = uploads.value.map((entry) => (entry.id === id ? { ...entry, ...changes } : entry))
  }

  function dismiss(id: number): void {
    controllers.delete(id)
    uploads.value = uploads.value.filter((entry) => entry.id !== id)
  }

  /**
   * Show ``name`` going up while ``send`` sends it, and return what it answers.
   *
   * ``send`` is handed what to report progress to and what cancels it. A
   * failure is kept on the list and thrown on; a cancellation leaves the list
   * and resolves to `null`, because changing one's mind is not an error.
   */
  async function track<T>(
    name: string,
    total: number,
    send: (progress: (sent: number) => void, signal: AbortSignal) => Promise<T>,
  ): Promise<T | null> {
    const id = next++
    const controller = new AbortController()
    controllers.set(id, controller)
    uploads.value = [...uploads.value, { id, name, sent: 0, total, error: null }]
    try {
      const answer = await send((sent) => update(id, { sent }), controller.signal)
      dismiss(id)
      return answer
    } catch (thrown) {
      if (isCancelled(thrown)) {
        dismiss(id)
        return null
      }
      controllers.delete(id)
      update(id, { error: thrown instanceof Error ? thrown.message : String(thrown) })
      throw thrown
    }
  }

  /** Show a file that was refused before it was sent, saying why. */
  function refuse(name: string, error: string): void {
    uploads.value = [...uploads.value, { id: next++, name, sent: 0, total: 0, error }]
  }

  /** Stop an upload still going. */
  function cancel(id: number): void {
    controllers.get(id)?.abort()
  }

  return { uploads, track, refuse, cancel, dismiss }
})
