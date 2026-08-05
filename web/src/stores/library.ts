import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { request } from '@/api/client'

export interface LibrarySummary {
  id: number
  type: string
  ownerId: number
  name: string
  version: number
  prefix: string
  /** Whether this account may change the library. Resolved by the server: a
   *  group can reserve editing for its administrators, and deciding that here
   *  would be a second implementation of a rule that already exists. */
  writable: boolean
}

export interface ItemEnvelope {
  key: string
  version: number
  data: Record<string, unknown> & {
    itemType: string
    title?: string
    parentItem?: string
    note?: string
    filename?: string
    contentType?: string
    linkMode?: string
    tags?: { tag: string; type?: number }[]
    collections?: string[]
  }
  meta: { creatorSummary?: string; parsedDate?: string; numChildren?: number }
}

export interface CollectionEnvelope {
  key: string
  version: number
  data: { key: string; name: string; parentCollection: string | false }
  meta: { numCollections: number; numItems: number }
}

export interface TagEntry {
  tag: string
  type: number
  numItems: number
}

/** A collection with its children, as the sidebar draws it. */
export interface CollectionNode extends CollectionEnvelope {
  children: CollectionNode[]
}

/** What the sidebar can have selected. */
export type Scope = 'top' | 'all' | 'trash'

/** How many items one page holds. */
export const PAGE_SIZE = 50

function tree(collections: CollectionEnvelope[]): CollectionNode[] {
  const nodes = new Map<string, CollectionNode>(
    collections.map((entry) => [entry.key, { ...entry, children: [] }]),
  )

  const roots: CollectionNode[] = []
  for (const node of nodes.values()) {
    const parentKey = node.data.parentCollection
    const parent = parentKey ? nodes.get(parentKey) : undefined
    // A collection whose parent is missing -- filtered out, or not yet synced --
    // is shown at the top rather than dropped, so nothing becomes unreachable.
    if (parent) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  }

  const byName = (a: CollectionNode, b: CollectionNode) =>
    a.data.name.localeCompare(b.data.name, undefined, { sensitivity: 'base' })
  const sort = (list: CollectionNode[]) => {
    list.sort(byName)
    list.forEach((node) => sort(node.children))
  }
  sort(roots)

  return roots
}

/**
 * The library being browsed, and what is selected in it.
 *
 * One store rather than several because the parts are not independent: picking
 * a collection resets the page, changing library invalidates the collections
 * and the tag list, and the detail pane follows the selection. Keeping that in
 * one place is what stops the three panes from disagreeing about what is being
 * looked at.
 *
 * Requests carry an `AbortController` for the same reason. Clicking through
 * collections faster than the server answers would otherwise leave whichever
 * response arrived last on screen, which is not necessarily the one asked for.
 */
export const useLibraryStore = defineStore('library', () => {
  const libraries = ref<LibrarySummary[]>([])
  const libraryId = ref<number | null>(null)

  const collections = ref<CollectionNode[]>([])
  const tags = ref<TagEntry[]>([])

  const items = ref<ItemEnvelope[]>([])
  const total = ref(0)
  const start = ref(0)

  const scope = ref<Scope>('top')
  const collectionKey = ref<string | null>(null)
  const selectedTags = ref<string[]>([])
  const search = ref('')
  const sort = ref('dateModified')
  const direction = ref<'asc' | 'desc'>('desc')

  const selected = ref<ItemEnvelope | null>(null)
  const children = ref<ItemEnvelope[]>([])

  const loading = ref(false)
  const failure = ref<string | null>(null)

  let itemsRequest: AbortController | null = null
  let childrenRequest: AbortController | null = null

  const library = computed(
    () => libraries.value.find((entry) => entry.id === libraryId.value) ?? null,
  )
  const hasMore = computed(() => start.value + items.value.length < total.value)
  const writable = computed(() => library.value?.writable === true)
  /**
   * The collections from the top of the tree down to ``key``, ``key`` last.
   *
   * Empty for a key the tree does not hold, which is a collection that was
   * filtered out or has just gone: a caller that shows a path gets a shorter
   * one rather than a wrong one.
   */
  function pathTo(key: string | null): CollectionNode[] {
    if (!key) return []

    const walk = (nodes: CollectionNode[], trail: CollectionNode[]): CollectionNode[] | null => {
      for (const node of nodes) {
        const here = [...trail, node]
        if (node.key === key) return here
        const found = walk(node.children, here)
        if (found) return found
      }
      return null
    }
    return walk(collections.value, []) ?? []
  }

  /** The collection the sidebar has selected, if it has one. */
  const selectedCollection = computed<CollectionNode | null>(
    () => pathTo(collectionKey.value).at(-1) ?? null,
  )
  const collectionName = computed(() => selectedCollection.value?.data.name ?? null)

  function itemsUrl(): string {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      start: String(start.value),
      scope: scope.value,
      sort: sort.value,
      direction: direction.value,
    })
    if (collectionKey.value) params.set('collection', collectionKey.value)
    if (search.value.trim()) params.set('q', search.value.trim())
    for (const tag of selectedTags.value) params.append('tag', tag)
    return `/web/libraries/${libraryId.value}/items?${params}`
  }

  async function loadLibraries(): Promise<void> {
    libraries.value = await request<LibrarySummary[]>('/web/libraries')
    if (libraries.value.length > 0 && libraryId.value === null) {
      await openLibrary(libraries.value[0].id)
    }
  }

  /** Switch libraries, discarding everything that described the previous one. */
  async function openLibrary(id: number): Promise<void> {
    libraryId.value = id
    collections.value = []
    tags.value = []
    collectionKey.value = null
    selectedTags.value = []
    scope.value = 'top'
    search.value = ''
    selected.value = null
    children.value = []
    start.value = 0

    await Promise.all([loadCollections(), loadTags(), loadItems()])
  }

  async function loadCollections(): Promise<void> {
    if (libraryId.value === null) return
    const payload = await request<{ collections: CollectionEnvelope[] }>(
      `/web/libraries/${libraryId.value}/collections`,
    )
    collections.value = tree(payload.collections)
  }

  /**
   * Make a collection, and open it.
   *
   * The tree is fetched again rather than patched: a new subcollection changes
   * how many its parent reports, and a count that disagrees with the tree under
   * it is worse than one extra request. Opening it afterwards is what the
   * desktop client does, and is almost always what was wanted next.
   *
   * Always in the library being browsed: the sidebar shows one library's
   * collections at a time, so the row this was reached from is in that library
   * and there is nowhere else for it to go.
   */
  async function createCollection(name: string, parentCollection?: string | null): Promise<void> {
    if (libraryId.value === null) return

    const created = await request<CollectionEnvelope>(
      `/web/libraries/${libraryId.value}/collections`,
      { method: 'POST', body: parentCollection ? { name, parentCollection } : { name } },
    )
    await loadCollections()
    await selectCollection(created.key)
  }

  /**
   * Remove a collection. Its subcollections move up; its items stay.
   *
   * If it was the one being shown, the view falls back to the whole library —
   * leaving the selection on a key the server no longer knows would list
   * nothing and say the collection was empty.
   */
  async function deleteCollection(key: string): Promise<void> {
    if (libraryId.value === null) return
    await request(`/web/libraries/${libraryId.value}/collections/${key}`, { method: 'DELETE' })
    await loadCollections()
    if (collectionKey.value === key) await selectCollection(null)
  }

  async function loadTags(): Promise<void> {
    if (libraryId.value === null) return
    const payload = await request<{ tags: TagEntry[] }>(`/web/libraries/${libraryId.value}/tags`)
    tags.value = payload.tags
  }

  async function loadItems({ append = false } = {}): Promise<void> {
    if (libraryId.value === null) return

    itemsRequest?.abort()
    const controller = new AbortController()
    itemsRequest = controller

    loading.value = true
    try {
      const payload = await request<{ total: number; items: ItemEnvelope[] }>(itemsUrl(), {
        signal: controller.signal,
      })
      items.value = append ? [...items.value, ...payload.items] : payload.items
      total.value = payload.total
      failure.value = null
    } catch (thrown) {
      if (controller.signal.aborted) return
      failure.value = thrown instanceof Error ? thrown.message : String(thrown)
    } finally {
      if (itemsRequest === controller) {
        itemsRequest = null
        loading.value = false
      }
    }
  }

  /** Re-run the query from the first page, which every filter change needs. */
  async function refresh(): Promise<void> {
    start.value = 0
    await loadItems()
  }

  async function loadMore(): Promise<void> {
    if (!hasMore.value || loading.value) return
    start.value = items.value.length
    await loadItems({ append: true })
  }

  async function selectScope(next: Scope): Promise<void> {
    scope.value = next
    collectionKey.value = null
    selected.value = null
    await refresh()
  }

  async function selectCollection(key: string | null): Promise<void> {
    collectionKey.value = key
    if (key) scope.value = 'top'
    selected.value = null
    await refresh()
  }

  async function toggleTag(tag: string): Promise<void> {
    selectedTags.value = selectedTags.value.includes(tag)
      ? selectedTags.value.filter((entry) => entry !== tag)
      : [...selectedTags.value, tag]
    await refresh()
  }

  async function setSearch(text: string): Promise<void> {
    search.value = text
    await refresh()
  }

  /** Sort by a column, reversing it when it is already the one in use. */
  async function sortBy(field: string): Promise<void> {
    if (sort.value === field) {
      direction.value = direction.value === 'asc' ? 'desc' : 'asc'
    } else {
      sort.value = field
      direction.value = field.startsWith('date') ? 'desc' : 'asc'
    }
    await refresh()
  }

  async function select(item: ItemEnvelope | null): Promise<void> {
    selected.value = item
    children.value = []
    if (!item || libraryId.value === null) return

    childrenRequest?.abort()
    const controller = new AbortController()
    childrenRequest = controller
    try {
      const payload = await request<{ items: ItemEnvelope[] }>(
        `/web/libraries/${libraryId.value}/items/${item.key}/children`,
        { signal: controller.signal },
      )
      // The selection may have moved on while this was in flight.
      if (selected.value?.key === item.key) {
        children.value = payload.items
      }
    } catch {
      // A detail pane without its child list is still useful; the list itself
      // reports anything that stops the library loading.
    } finally {
      if (childrenRequest === controller) childrenRequest = null
    }
  }

  function fileUrl(key: string, { download = false } = {}): string {
    const suffix = download ? '?download=true' : ''
    return `/web/libraries/${libraryId.value}/items/${key}/file${suffix}`
  }

  function reset(): void {
    libraries.value = []
    libraryId.value = null
    collections.value = []
    tags.value = []
    items.value = []
    selected.value = null
    children.value = []
    total.value = 0
    start.value = 0
    failure.value = null
  }

  return {
    libraries,
    libraryId,
    library,
    collections,
    collectionKey,
    collectionName,
    selectedCollection,
    pathTo,
    tags,
    selectedTags,
    items,
    total,
    scope,
    search,
    sort,
    direction,
    selected,
    children,
    loading,
    failure,
    hasMore,
    writable,
    loadLibraries,
    openLibrary,
    loadCollections,
    createCollection,
    deleteCollection,
    loadTags,
    loadItems,
    loadMore,
    refresh,
    selectScope,
    selectCollection,
    toggleTag,
    setSearch,
    sortBy,
    select,
    fileUrl,
    reset,
  }
})
