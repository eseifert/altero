import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError, request } from '@/api/client'
import type { ItemEnvelope } from '@/stores/library'

/** Who may read a profile page. The same three the server stores. */
export type Visibility = 'public' | 'users' | 'private'

export interface Profile {
  username: string
  /** The display name, or the username when there is none. */
  displayName: string
  numPublications: number
  /** Whether the reader is the person whose page this is. */
  owner: boolean
  /** The owner's setting, sent to the owner alone and null to everybody else. */
  visibility: Visibility | null
}

/** How many publications are asked for at a time. The server's own cap is 100. */
const PAGE = 25

/**
 * One person's published work, as a page anybody may be reading.
 *
 * Deliberately not the library store. That one holds a signed-in account's
 * libraries, collections, tags and selection, and every request it makes needs
 * a cookie; this holds one list that a stranger can read, and the two would
 * only ever share the word "items". Keeping them apart is also what keeps a
 * profile page from loading a library the visitor has no business seeing.
 *
 * A profile that may not be read is reported by the server as absent, exactly
 * as an unclaimed name is, so `missing` covers both -- see
 * `api/routes/webprofile.py` for why it does not distinguish them.
 */
export const useProfileStore = defineStore('profile', () => {
  const profile = ref<Profile | null>(null)
  const items = ref<ItemEnvelope[]>([])
  const total = ref(0)
  const busy = ref(false)
  const loadingMore = ref(false)
  const missing = ref(false)
  const error = ref<string | null>(null)

  /** The item whose details are open, and what hangs off it. */
  const opened = ref<string | null>(null)
  const children = ref<ItemEnvelope[]>([])

  const hasMore = computed(() => items.value.length < total.value)

  function reset(): void {
    profile.value = null
    items.value = []
    total.value = 0
    missing.value = false
    error.value = null
    opened.value = null
    children.value = []
  }

  function record(thrown: unknown): void {
    if (thrown instanceof ApiError && thrown.status === 404) {
      missing.value = true
      return
    }
    error.value = thrown instanceof Error ? thrown.message : String(thrown)
  }

  async function load(username: string): Promise<void> {
    reset()
    busy.value = true
    try {
      profile.value = await request<Profile>(`/web/profiles/${encodeURIComponent(username)}`)
      await fetchPage(username, 0)
    } catch (thrown) {
      record(thrown)
    } finally {
      busy.value = false
    }
  }

  async function fetchPage(username: string, start: number): Promise<void> {
    const payload = await request<{ total: number; items: ItemEnvelope[] }>(
      `/web/profiles/${encodeURIComponent(username)}/items?limit=${PAGE}&start=${start}`,
    )
    total.value = payload.total
    items.value = start === 0 ? payload.items : [...items.value, ...payload.items]
  }

  /** Fetch the next page, leaving what is already on screen where it is. */
  async function more(username: string): Promise<void> {
    if (loadingMore.value || !hasMore.value) return
    loadingMore.value = true
    try {
      await fetchPage(username, items.value.length)
    } catch (thrown) {
      record(thrown)
    } finally {
      loadingMore.value = false
    }
  }

  /**
   * Open one publication, or close it if it was already open.
   *
   * The children are fetched when it opens rather than with the list: a page
   * of twenty-five items would otherwise make twenty-six requests to show
   * files nobody has asked to see yet.
   */
  async function open(username: string, key: string): Promise<void> {
    if (opened.value === key) {
      opened.value = null
      children.value = []
      return
    }

    opened.value = key
    children.value = []
    try {
      const payload = await request<{ items: ItemEnvelope[] }>(
        `/web/profiles/${encodeURIComponent(username)}/items/${key}/children`,
      )
      // The reader may have moved on while this was in flight.
      if (opened.value === key) {
        children.value = payload.items
      }
    } catch (thrown) {
      record(thrown)
    }
  }

  /** Where an attachment's bytes are, for a link the browser follows itself. */
  function fileUrl(username: string, key: string, options: { download?: boolean } = {}): string {
    const query = options.download ? '?download=true' : ''
    return `/web/profiles/${encodeURIComponent(username)}/items/${key}/file${query}`
  }

  return {
    profile,
    items,
    total,
    busy,
    loadingMore,
    missing,
    error,
    opened,
    children,
    hasMore,
    load,
    more,
    open,
    fileUrl,
    reset,
  }
})
