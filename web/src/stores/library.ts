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

/**
 * What the sidebar can have selected.
 *
 * ``all`` is the whole library including child notes and attachments. The
 * sidebar has no row for it -- neither does Zotero's own web library -- but the
 * server takes it, and the store is the shape of what the server takes.
 */
export type Scope =
  | 'top'
  | 'all'
  | 'trash'
  | 'publications'
  | 'unfiled'
  | 'duplicates'
  | 'recentlyread'

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
  const selectedCollection = computed<CollectionNode | null>(() => {
    /* Indexed rather than `.at(-1)`, which Safari learnt in 15.4 and the
       oldest browser this interface supports has not. */
    const trail = pathTo(collectionKey.value)
    return trail.length ? trail[trail.length - 1] : null
  })
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
   * Rename a collection, move it, or both.
   *
   * A patch: whatever is not sent keeps what is stored. The tree is read again
   * rather than edited in place, because a move changes how many collections
   * two parents report and a name changes where the collection sorts among its
   * siblings, and neither is worth reproducing here.
   */
  async function updateCollection(
    key: string,
    changes: { name?: string; parentCollection?: string | null },
  ): Promise<void> {
    if (libraryId.value === null) return
    await request(`/web/libraries/${libraryId.value}/collections/${key}`, {
      method: 'PATCH',
      body: changes,
    })
    await loadCollections()
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

  /**
   * Rename a tag throughout the library, and return how many items changed.
   *
   * The panel is always read again: a rename onto a name already in use leaves
   * one tag where there were two, and every count on it can have moved, which
   * no amount of editing the list in place arrives at.
   *
   * A tag that was narrowing the list keeps its selection under the new name,
   * and the list is re-run because the filter has changed. The alternative is a
   * list filtered by a tag that no longer exists, which shows nothing and says
   * the library is empty. Otherwise the middle pane is untouched — it lists
   * titles, creators and dates, and none of those is a tag — and only the open
   * item, which does print its tags, is fetched again.
   */
  async function renameTag(oldName: string, newName: string): Promise<number> {
    if (libraryId.value === null) return 0

    const renamed = await request<TagEntry & { itemsChanged: number }>(
      `/web/libraries/${libraryId.value}/tags/${encodeURIComponent(oldName)}`,
      { method: 'PATCH', body: { tag: newName } },
    )

    const filtering = selectedTags.value.includes(oldName)
    if (filtering) {
      const kept = selectedTags.value.filter((entry) => entry !== oldName)
      selectedTags.value = kept.includes(renamed.tag) ? kept : [...kept, renamed.tag]
    }

    await loadTags()
    if (filtering) {
      await refresh()
    } else {
      await reloadSelected()
    }
    return renamed.itemsChanged
  }

  /**
   * Writes to one item: where it is filed, whether it is in the trash, and
   * whether it exists at all.
   *
   * Every one of them re-runs the query rather than editing the list in place.
   * A trashed item leaves the list it was in, a filed one may leave the
   * collection being shown, and both change the counts beside the collections
   * in the sidebar -- there is no version of "patch what is on screen" that
   * gets all of that right, and a list that disagrees with the library is
   * worse than a request.
   */
  async function afterItemWrite(): Promise<void> {
    await Promise.all([refresh(), loadCollections()])
    /* The open item may have gone, or moved out of what is being shown. If it
       is still in the list, it is read again; if it is not, the pane closes,
       because a detail pane describing something the list no longer holds is
       the one pane that can lie. */
    const key = selected.value?.key
    if (!key) return
    if (items.value.some((entry) => entry.key === key)) {
      await reloadSelected()
    } else {
      selected.value = null
      children.value = []
    }
  }

  /** Put ``key`` into collections, take it out of others, or both. */
  async function fileItem(
    key: string,
    changes: { add?: string[]; remove?: string[] },
  ): Promise<void> {
    if (libraryId.value === null) return
    const body: Record<string, string[]> = {}
    if (changes.add?.length) body.addCollections = changes.add
    if (changes.remove?.length) body.removeCollections = changes.remove
    if (!Object.keys(body).length) return

    await request(`/web/libraries/${libraryId.value}/items/${key}`, { method: 'PATCH', body })
    await afterItemWrite()
  }

  /** Move ``key`` to the trash, or bring it back out. */
  async function trashItem(key: string, deleted = true): Promise<void> {
    if (libraryId.value === null) return
    await request(`/web/libraries/${libraryId.value}/items/${key}`, {
      method: 'PATCH',
      body: { deleted },
    })
    await afterItemWrite()
  }

  /** Remove ``key`` for good. The server refuses this outside the trash. */
  async function deleteItem(key: string): Promise<void> {
    if (libraryId.value === null) return
    await request(`/web/libraries/${libraryId.value}/items/${key}`, { method: 'DELETE' })
    await afterItemWrite()
  }

  /** Empty the trash, and return how many items went. */
  async function emptyTrash(): Promise<number> {
    if (libraryId.value === null) return 0
    const payload = await request<{ deleted: number }>(
      `/web/libraries/${libraryId.value}/trash`,
      { method: 'DELETE' },
    )
    await afterItemWrite()
    return payload.deleted
  }

  /**
   * Copy ``key`` into another library, optionally into a collection there.
   *
   * Nothing on screen changes: the library being read is the one the item came
   * from, and it is untouched. Only its version in `libraries` is stale
   * afterwards, so that is read again.
   */
  async function copyItem(key: string, target: number, collection?: string | null): Promise<void> {
    if (libraryId.value === null) return
    const body: Record<string, unknown> = { library: target }
    if (collection) body.collection = collection

    await request(`/web/libraries/${libraryId.value}/items/${key}/copy`, { method: 'POST', body })
    libraries.value = await request<LibrarySummary[]>('/web/libraries')
  }

  /** Read the open item again, so a pane showing the old name stops. */
  async function reloadSelected(): Promise<void> {
    const key = selected.value?.key
    if (!key || libraryId.value === null) return

    try {
      const fresh = await request<ItemEnvelope>(
        `/web/libraries/${libraryId.value}/items/${key}`,
      )
      selected.value = fresh
      const index = items.value.findIndex((entry) => entry.key === key)
      if (index >= 0) items.value[index] = fresh
    } catch {
      // The pane keeps what it has. It is one stale line in a list of fields,
      // against a failure the reader can do nothing about.
    }
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
    updateCollection,
    deleteCollection,
    loadTags,
    renameTag,
    loadItems,
    loadMore,
    fileItem,
    trashItem,
    deleteItem,
    emptyTrash,
    copyItem,
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
