import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError, request } from '@/api/client'
import type { CollectionEnvelope, ItemEnvelope } from '@/stores/library'

/** What the link is a link to. */
export interface SharedCollection {
  collection: string
  library: string
  subcollections: boolean
  files: boolean
  numItems: number
  /** ISO 8601, or null for a link that never stops working. */
  expires: string | null
}

/** How many items are asked for at a time. The server's own cap is 100. */
const PAGE = 25

/**
 * One shared collection, read by whoever holds the link.
 *
 * Deliberately not the library store, for the reason the profile store is not
 * either: that one holds a signed-in account's libraries and every request it
 * makes needs a cookie, while this holds one list a stranger can read. Keeping
 * them apart is what keeps a shared page from loading a library the visitor
 * has no business seeing.
 *
 * A token that never was, one that was revoked, one that has expired and one
 * whose collection has been thrown away all come back as 404, so `missing`
 * covers all four -- see `api/routes/webshares.py` for why the server does not
 * distinguish them.
 */
export const useSharedStore = defineStore('shared', () => {
  const shared = ref<SharedCollection | null>(null)
  const collections = ref<CollectionEnvelope[]>([])
  const items = ref<ItemEnvelope[]>([])
  const total = ref(0)
  const busy = ref(false)
  const loadingMore = ref(false)
  const missing = ref(false)
  const error = ref<string | null>(null)

  /** Which collection inside the shared one is showing, or null for all of it. */
  const inside = ref<string | null>(null)
  const search = ref('')

  /** The item whose details are open, and what hangs off it. */
  const opened = ref<string | null>(null)
  const children = ref<ItemEnvelope[]>([])

  const hasMore = computed(() => items.value.length < total.value)

  function reset(): void {
    shared.value = null
    collections.value = []
    items.value = []
    total.value = 0
    missing.value = false
    error.value = null
    inside.value = null
    search.value = ''
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

  function base(token: string): string {
    return `/web/shared/${encodeURIComponent(token)}`
  }

  async function load(token: string): Promise<void> {
    reset()
    busy.value = true
    try {
      shared.value = await request<SharedCollection>(base(token))
      collections.value = (
        await request<{ collections: CollectionEnvelope[] }>(`${base(token)}/collections`)
      ).collections
      await fetchPage(token, 0)
    } catch (thrown) {
      record(thrown)
    } finally {
      busy.value = false
    }
  }

  function query(start: number): string {
    const parameters = new URLSearchParams({ limit: String(PAGE), start: String(start) })
    if (inside.value) parameters.set('collection', inside.value)
    if (search.value.trim()) parameters.set('q', search.value.trim())
    return parameters.toString()
  }

  async function fetchPage(token: string, start: number): Promise<void> {
    const payload = await request<{ total: number; items: ItemEnvelope[] }>(
      `${base(token)}/items?${query(start)}`,
    )
    total.value = payload.total
    items.value = start === 0 ? payload.items : [...items.value, ...payload.items]
  }

  /** Redraw the list from the top, after a search or a change of collection. */
  async function refresh(token: string): Promise<void> {
    busy.value = true
    opened.value = null
    children.value = []
    try {
      await fetchPage(token, 0)
    } catch (thrown) {
      record(thrown)
    } finally {
      busy.value = false
    }
  }

  async function more(token: string): Promise<void> {
    if (loadingMore.value || !hasMore.value) return
    loadingMore.value = true
    try {
      await fetchPage(token, items.value.length)
    } catch (thrown) {
      record(thrown)
    } finally {
      loadingMore.value = false
    }
  }

  /**
   * Open one item, or close it if it was already open.
   *
   * The children are fetched when it opens rather than with the list, for the
   * reason the profile page gives: a page of twenty-five items would otherwise
   * make twenty-six requests to show files nobody has asked to see.
   */
  async function open(token: string, key: string): Promise<void> {
    if (opened.value === key) {
      opened.value = null
      children.value = []
      return
    }

    opened.value = key
    children.value = []
    try {
      const payload = await request<{ items: ItemEnvelope[] }>(
        `${base(token)}/items/${key}/children`,
      )
      if (opened.value === key) {
        children.value = payload.items
      }
    } catch (thrown) {
      record(thrown)
    }
  }

  /** Where an attachment's bytes are, for a link the browser follows itself. */
  function fileUrl(token: string, key: string, options: { download?: boolean } = {}): string {
    const suffix = options.download ? '?download=true' : ''
    return `${base(token)}/items/${key}/file${suffix}`
  }

  return {
    shared,
    collections,
    items,
    total,
    busy,
    loadingMore,
    missing,
    error,
    inside,
    search,
    opened,
    children,
    hasMore,
    load,
    refresh,
    more,
    open,
    fileUrl,
    reset,
  }
})
