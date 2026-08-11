import { defineStore } from 'pinia'
import { ref } from 'vue'

import { ApiError, request } from '@/api/client'

/**
 * One link that shows a collection to whoever holds it.
 *
 * `url` is present exactly once, on the answer to the request that made the
 * link, and never again: the server does not store anything it could be
 * reconstructed from. A link that is lost is replaced rather than recovered,
 * which is the same rule the invitation links follow.
 */
export interface CollectionShare {
  id: number
  /** The collection's key, and its name at the moment the list was drawn. */
  collection: string
  collectionName: string
  subcollections: boolean
  files: boolean
  /** ISO 8601, UTC. Render with `formatDate`, never `toLocaleString`. */
  created: string
  expires: string | null
  lastUsed: string | null
  createdBy: number
  /** The link itself. Only ever on a freshly made share. */
  url?: string
}

export interface ShareTerms {
  subcollections: boolean
  files: boolean
  /** ISO 8601, or null for a link that never stops working. */
  expires: string | null
}

/**
 * The links out of one library.
 *
 * Held per library because that is the question somebody has -- "what have I
 * given away" -- and because reading the list takes write access to the
 * library, which is a per-library answer.
 */
export const useShareStore = defineStore('shares', () => {
  const shares = ref<CollectionShare[]>([])
  const busy = ref(false)
  const error = ref<string | null>(null)
  /** The link just made, shown once and then dismissed by the dialog. */
  const issued = ref<CollectionShare | null>(null)

  function message(thrown: unknown): string {
    return thrown instanceof ApiError ? thrown.message : String(thrown)
  }

  async function attempt<T>(work: () => Promise<T>): Promise<{ ok: true; value: T } | { ok: false }> {
    busy.value = true
    error.value = null
    try {
      return { ok: true, value: await work() }
    } catch (thrown) {
      error.value = message(thrown)
      return { ok: false }
    } finally {
      busy.value = false
    }
  }

  async function load(libraryId: number): Promise<void> {
    const outcome = await attempt(() =>
      request<{ shares: CollectionShare[] }>(`/web/libraries/${libraryId}/shares`),
    )
    if (outcome.ok) {
      shares.value = outcome.value.shares
    }
  }

  async function create(
    libraryId: number,
    collectionKey: string,
    terms: ShareTerms,
  ): Promise<CollectionShare | null> {
    const outcome = await attempt(() =>
      request<CollectionShare>(
        `/web/libraries/${libraryId}/collections/${collectionKey}/shares`,
        { method: 'POST', body: terms },
      ),
    )
    if (!outcome.ok) {
      return null
    }
    issued.value = outcome.value
    await load(libraryId)
    return outcome.value
  }

  async function update(
    libraryId: number,
    shareId: number,
    changes: Partial<ShareTerms> & { neverExpires?: boolean },
  ): Promise<void> {
    const outcome = await attempt(() =>
      request(`/web/shares/${shareId}`, { method: 'PATCH', body: changes }),
    )
    if (outcome.ok) {
      await load(libraryId)
    }
  }

  async function revoke(libraryId: number, shareId: number): Promise<void> {
    const outcome = await attempt(() => request(`/web/shares/${shareId}`, { method: 'DELETE' }))
    if (outcome.ok) {
      if (issued.value?.id === shareId) {
        issued.value = null
      }
      await load(libraryId)
    }
  }

  function forget(): void {
    issued.value = null
    error.value = null
  }

  function reset(): void {
    shares.value = []
    issued.value = null
    error.value = null
  }

  return { shares, busy, error, issued, load, create, update, revoke, forget, reset }
})
