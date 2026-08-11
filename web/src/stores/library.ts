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
    rights?: string
    /** Emitted only when true, as the API emits it. */
    inPublications?: boolean
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

  /*
   * Two things, and they are not the same thing.
   *
   * `selection` is every row picked out, and is what the errands act on.
   * `selected` is the one row the detail pane describes, which exists only when
   * exactly one is picked out: a pane showing the fields of one item out of five
   * would be describing a row nobody singled out, and a pane showing five items'
   * fields at once is a field editor, which this is not.
   */
  const selection = ref<string[]>([])
  const selected = ref<ItemEnvelope | null>(null)
  const children = ref<ItemEnvelope[]>([])

  /** The row a Shift-click measures its range from. */
  const anchor = ref<string | null>(null)

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
   * The rows picked out, in the order the list draws them.
   *
   * Derived from the list rather than stored in click order, because that is the
   * order everything downstream means: "these three" reads top to bottom, and a
   * key whose row has gone simply is not here.
   */
  const selectedItems = computed(() =>
    items.value.filter((entry) => selection.value.includes(entry.key)),
  )
  const selectionKeys = computed(() => selectedItems.value.map((entry) => entry.key))
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

  /** What the list is showing: the scope, the collection, the search, the tags. */
  function viewParams(): URLSearchParams {
    const params = new URLSearchParams({
      scope: scope.value,
      sort: sort.value,
      direction: direction.value,
    })
    if (collectionKey.value) params.set('collection', collectionKey.value)
    if (search.value.trim()) params.set('q', search.value.trim())
    for (const tag of selectedTags.value) params.append('tag', tag)
    return params
  }

  function itemsUrl(): string {
    const params = viewParams()
    params.set('limit', String(PAGE_SIZE))
    params.set('start', String(start.value))
    return `/web/libraries/${libraryId.value}/items?${params}`
  }

  /**
   * Where the browser fetches an export of what is being looked at.
   *
   * The list's own query, so the file holds what the screen holds — narrowed to
   * `keys` when rows are picked out, which is the difference between the
   * client's Export Library… and its Export Items…. `name` is what to call the
   * file: the browser knows the view's name in the reader's language and the
   * server does not.
   *
   * A URL rather than a fetch, as the archive in settings is: the browser
   * streams it to disk and shows its own progress, and an export is as long as
   * the library it came from.
   */
  function exportUrl(
    format: string,
    { keys, name, whole = false }: { keys?: string[]; name?: string; whole?: boolean } = {},
  ): string {
    /* `whole` is the library rather than the view: the top level of it, with
       no collection, no search and no tags. It is what somebody means by "all
       of it" while standing in a collection, and it cannot be expressed by
       leaving parameters off, since the view supplies them. */
    const params = whole
      ? new URLSearchParams({ scope: 'top', sort: sort.value, direction: direction.value })
      : viewParams()
    params.set('format', format)
    if (keys?.length) params.set('itemKey', keys.join(','))
    if (name) params.set('name', name)
    return `/web/libraries/${libraryId.value}/items/export?${params}`
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
    selection.value = []
    anchor.value = null
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
    /* Rows that have left the list leave the selection with them: a count in
       the pane that includes items nothing on screen shows is a count the
       reader cannot check, and the next errand would act on them regardless. */
    selection.value = selectionKeys.value
    if (!selection.value.includes(anchor.value ?? '')) anchor.value = null
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

  /**
   * Put ``keys`` into collections, take them out of others, or both.
   *
   * One request however many rows, because that is one new library version and
   * one thing the reader did. The same call carries a selection of one, so
   * there is no second path for the ordinary case to drift away from.
   */
  async function fileItems(
    keys: string[],
    changes: { add?: string[]; remove?: string[] },
  ): Promise<void> {
    if (libraryId.value === null || !keys.length) return
    const body: Record<string, unknown> = { items: keys }
    if (changes.add?.length) body.addCollections = changes.add
    if (changes.remove?.length) body.removeCollections = changes.remove
    if (Object.keys(body).length === 1) return

    await request(`/web/libraries/${libraryId.value}/items`, { method: 'PATCH', body })
    await afterItemWrite()
  }

  /** Move ``keys`` to the trash, or bring them back out. */
  async function trashItems(keys: string[], deleted = true): Promise<void> {
    if (libraryId.value === null || !keys.length) return
    await request(`/web/libraries/${libraryId.value}/items`, {
      method: 'PATCH',
      body: { items: keys, deleted },
    })
    await afterItemWrite()
  }

  /** Remove ``keys`` for good. The server refuses this outside the trash, and
   *  refuses the whole selection if any one of them is outside it. */
  async function deleteItems(keys: string[]): Promise<void> {
    if (libraryId.value === null || !keys.length) return
    const named = new URLSearchParams({ itemKey: keys.join(',') })
    await request(`/web/libraries/${libraryId.value}/items?${named}`, { method: 'DELETE' })
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
   * Read one item's notes and attachments, without opening it.
   *
   * `select` fetches these for the item in the detail pane; this is for the
   * one being published, which is whichever row was carried and need not be
   * the one on screen. The wizard has to know what it is offering to include
   * before it asks — a checkbox for files on an item that has none is a
   * question with no answer.
   */
  async function childrenOf(key: string): Promise<ItemEnvelope[]> {
    if (libraryId.value === null) return []
    const payload = await request<{ items: ItemEnvelope[] }>(
      `/web/libraries/${libraryId.value}/items/${key}/children`,
    )
    return payload.items
  }

  /**
   * Write the fields of ``key`` the browser is allowed to write.
   *
   * One field today — Rights, which is a published work's licence — and the
   * version is sent with it. The server refuses a stale one rather than
   * letting a page that has sat open all afternoon type over what somebody
   * else changed; the other item writes need no such thing, being errands the
   * server works out against what is stored.
   */
  async function editItem(key: string, fields: Record<string, string>): Promise<void> {
    if (libraryId.value === null) return
    const current = items.value.find((entry) => entry.key === key) ?? selected.value
    await request(`/web/libraries/${libraryId.value}/items/${key}`, {
      method: 'PATCH',
      body: { fields, version: current?.version },
    })
    await afterItemWrite()
  }

  /** Put ``key`` into My Publications on the terms the wizard collected. */
  async function publishItem(
    key: string,
    terms: {
      includeFiles: boolean
      includeNotes: boolean
      license: string | null
      keepRights: boolean
    },
  ): Promise<void> {
    if (libraryId.value === null) return
    await request(`/web/libraries/${libraryId.value}/publications/items/${key}`, {
      method: 'PUT',
      body: terms,
    })
    await afterItemWrite()
  }

  /**
   * Take ``key`` out of My Publications, with its children.
   *
   * The item stays in the library and keeps everything it holds; only its
   * place in the published list goes. The list is read again all the same,
   * because in the My Publications view that place *is* the row.
   */
  async function unpublishItem(key: string): Promise<void> {
    if (libraryId.value === null) return
    await request(`/web/libraries/${libraryId.value}/publications/items/${key}`, {
      method: 'DELETE',
    })
    await afterItemWrite()
  }

  /**
   * Copy ``keys`` into another library, optionally into a collection there.
   *
   * Nothing on screen changes: the library being read is the one the items came
   * from, and it is untouched. Only its version in `libraries` is stale
   * afterwards, so that is read again.
   */
  async function copyItems(
    keys: string[],
    target: number,
    collection?: string | null,
  ): Promise<void> {
    if (libraryId.value === null || !keys.length) return
    const body: Record<string, unknown> = { items: keys, library: target }
    if (collection) body.collection = collection

    await request(`/web/libraries/${libraryId.value}/items/copy`, { method: 'POST', body })
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
    selection.value = []
    anchor.value = null
    selected.value = null
    await refresh()
  }

  async function selectCollection(key: string | null): Promise<void> {
    collectionKey.value = key
    if (key) scope.value = 'top'
    selection.value = []
    anchor.value = null
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

  /**
   * Pick out one row and nothing else, which is what an ordinary click means.
   *
   * The anchor moves here and only here: a range is measured from the last row
   * chosen outright, so Shift-clicking twice from the same starting row grows
   * and shrinks one range rather than walking the anchor along behind it.
   */
  async function select(item: ItemEnvelope | null): Promise<void> {
    selection.value = item ? [item.key] : []
    anchor.value = item?.key ?? null
    await open(item)
  }

  /**
   * Add a row to the selection, or take it out again.
   *
   * The detail pane follows: back to one row and it describes that row, more
   * than one and there is no single row to describe.
   */
  async function toggleSelected(item: ItemEnvelope): Promise<void> {
    selection.value = selection.value.includes(item.key)
      ? selection.value.filter((key) => key !== item.key)
      : [...selection.value, item.key]
    anchor.value = item.key
    await followSelection()
  }

  /**
   * Everything between the anchor and ``item``, inclusive.
   *
   * Replacing the selection rather than adding to it, which is what a range
   * means: Shift-clicking a nearer row shrinks the range instead of leaving the
   * rows beyond it picked out with nothing on screen saying why.
   */
  async function extendSelection(item: ItemEnvelope): Promise<void> {
    const from = items.value.findIndex((entry) => entry.key === anchor.value)
    const to = items.value.findIndex((entry) => entry.key === item.key)
    if (to < 0) return
    if (from < 0) {
      await select(item)
      return
    }

    const [first, last] = from <= to ? [from, to] : [to, from]
    selection.value = items.value.slice(first, last + 1).map((entry) => entry.key)
    await followSelection()
  }

  /** Every row loaded. Not every row there is: the list pages, and a promise to
   *  act on what has not been fetched is one the interface cannot keep. */
  async function selectAll(): Promise<void> {
    selection.value = items.value.map((entry) => entry.key)
    anchor.value = items.value.length ? items.value[0].key : null
    await followSelection()
  }

  async function clearSelection(): Promise<void> {
    selection.value = []
    anchor.value = null
    await open(null)
  }

  /** Open the one row picked out, or close the pane when there is not one. */
  async function followSelection(): Promise<void> {
    const keys = selectionKeys.value
    if (keys.length !== 1) {
      await open(null)
      return
    }
    if (selected.value?.key === keys[0]) return
    await open(items.value.find((entry) => entry.key === keys[0]) ?? null)
  }

  async function open(item: ItemEnvelope | null): Promise<void> {
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
    selection.value = []
    anchor.value = null
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
    selection,
    selectedItems,
    selectionKeys,
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
    fileItems,
    trashItems,
    deleteItems,
    emptyTrash,
    copyItems,
    childrenOf,
    editItem,
    publishItem,
    unpublishItem,
    refresh,
    selectScope,
    selectCollection,
    toggleTag,
    setSearch,
    sortBy,
    select,
    toggleSelected,
    extendSelection,
    selectAll,
    clearSelection,
    fileUrl,
    exportUrl,
    reset,
  }
})
