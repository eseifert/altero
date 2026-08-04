import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useLibraryStore } from './library'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const LIBRARIES = [
  { id: 1, type: 'user', ownerId: 1, name: 'Ada', version: 4, prefix: '/users/1' },
  { id: 2, type: 'group', ownerId: 100, name: 'Analytical Engine', version: 9, prefix: '/groups/100' },
]

function item(key: string, title: string) {
  return { key, version: 1, data: { itemType: 'book', title }, meta: {} }
}

function collection(key: string, name: string, parent: string | false = false) {
  return {
    key,
    version: 1,
    data: { key, name, parentCollection: parent },
    meta: { numCollections: 0, numItems: 0 },
  }
}

/** Answer each endpoint with something plausible, recording what was asked. */
function respond(overrides: Record<string, unknown> = {}) {
  requestMock.mockImplementation((path: string) => {
    for (const [fragment, payload] of Object.entries(overrides)) {
      if (path.includes(fragment)) return Promise.resolve(payload)
    }
    if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
    if (path.includes('/collections')) return Promise.resolve({ collections: [] })
    if (path.includes('/tags')) return Promise.resolve({ tags: [] })
    if (path.includes('/children')) return Promise.resolve({ items: [] })
    return Promise.resolve({ total: 0, items: [] })
  })
}

/** The item-listing URLs the store asked for, in order. */
function itemRequests(): string[] {
  return requestMock.mock.calls
    .map(([path]) => path as string)
    .filter((path) => path.includes('/items?'))
}

beforeEach(() => {
  setActivePinia(createPinia())
  requestMock.mockReset()
  respond()
})

describe('opening a library', () => {
  it('opens the first one it is given', async () => {
    const store = useLibraryStore()

    await store.loadLibraries()

    expect(store.libraryId).toBe(1)
    expect(store.library?.name).toBe('Ada')
  })

  it('asks for the top level, which is what the client shows', async () => {
    const store = useLibraryStore()

    await store.loadLibraries()

    expect(itemRequests()[0]).toContain('scope=top')
  })

  it('discards the previous library when switching', async () => {
    /* A collection key belongs to one library. Carrying it across would filter
       the new library by a collection it does not have. */
    respond({ '/collections': { collections: [collection('CCCC2345', 'Papers')] } })
    const store = useLibraryStore()
    await store.loadLibraries()
    await store.selectCollection('CCCC2345')
    await store.toggleTag('toread')

    await store.openLibrary(2)

    expect(store.collectionKey).toBeNull()
    expect(store.selectedTags).toEqual([])
    expect(store.scope).toBe('top')
  })
})

describe('the collection tree', () => {
  it('nests children under their parent', async () => {
    respond({
      '/collections': {
        collections: [
          collection('PPPP2345', 'Papers'),
          collection('CCCC2345', 'Drafts', 'PPPP2345'),
        ],
      },
    })
    const store = useLibraryStore()

    await store.loadLibraries()

    expect(store.collections).toHaveLength(1)
    expect(store.collections[0].children[0].data.name).toBe('Drafts')
  })

  it('keeps a collection whose parent is missing at the top level', async () => {
    /* Otherwise it would be in the tree but drawn nowhere, and the items in it
       unreachable. */
    respond({
      '/collections': { collections: [collection('CCCC2345', 'Orphan', 'GONE2345')] },
    })
    const store = useLibraryStore()

    await store.loadLibraries()

    expect(store.collections.map((node) => node.data.name)).toEqual(['Orphan'])
  })

  it('names the selected collection for the heading', async () => {
    respond({ '/collections': { collections: [collection('CCCC2345', 'Papers')] } })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.selectCollection('CCCC2345')

    expect(store.collectionName).toBe('Papers')
  })
})

describe('filtering', () => {
  it('passes a collection, tags and a search to the server', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.selectCollection('CCCC2345')
    await store.toggleTag('toread')
    await store.setSearch('whales')

    const last = itemRequests().at(-1) ?? ''
    expect(last).toContain('collection=CCCC2345')
    expect(last).toContain('tag=toread')
    expect(last).toContain('q=whales')
  })

  it('turns a tag off again', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.toggleTag('toread')
    await store.toggleTag('toread')

    expect(store.selectedTags).toEqual([])
    expect(itemRequests().at(-1)).not.toContain('tag=')
  })

  it('goes back to the first page whenever the filter changes', async () => {
    /* Page four of the old query is not page four of the new one, and asking
       for it shows an empty list for a search that has results. */
    respond({ '/items?': { total: 100, items: [item('AAAA2345', 'One')] } })
    const store = useLibraryStore()
    await store.loadLibraries()
    await store.loadMore()

    await store.setSearch('whales')

    expect(itemRequests().at(-1)).toContain('start=0')
  })

  it('selects the trash as its own view', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.selectScope('trash')

    expect(itemRequests().at(-1)).toContain('scope=trash')
  })

  it('clears the collection when a scope is chosen', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()
    await store.selectCollection('CCCC2345')

    await store.selectScope('all')

    expect(store.collectionKey).toBeNull()
    expect(itemRequests().at(-1)).not.toContain('collection=')
  })
})

describe('sorting', () => {
  it('reverses a column that is already the sort', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.sortBy('title')
    expect(store.direction).toBe('asc')

    await store.sortBy('title')
    expect(store.direction).toBe('desc')
  })

  it('starts a date column at the newest', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.sortBy('date')

    expect(store.sort).toBe('date')
    expect(store.direction).toBe('desc')
  })
})

describe('paging', () => {
  it('appends the next page rather than replacing the list', async () => {
    respond({ '/items?': { total: 4, items: [item('AAAA2345', 'One')] } })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.loadMore()

    expect(store.items).toHaveLength(2)
    expect(itemRequests().at(-1)).toContain('start=1')
  })

  it('stops when everything has been fetched', async () => {
    respond({ '/items?': { total: 1, items: [item('AAAA2345', 'One')] } })
    const store = useLibraryStore()
    await store.loadLibraries()

    expect(store.hasMore).toBe(false)
  })
})

describe('selection', () => {
  it('loads an item’s children when it is selected', async () => {
    const child = { key: 'BBBB2345', version: 1, data: { itemType: 'note', note: '<p>Hi</p>' }, meta: {} }
    respond({ '/children': { items: [child] } })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.select(item('AAAA2345', 'One'))

    expect(store.children).toHaveLength(1)
  })

  it('drops the children when the selection is cleared', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()
    await store.select(item('AAAA2345', 'One'))

    await store.select(null)

    expect(store.selected).toBeNull()
    expect(store.children).toEqual([])
  })

  it('survives a failure to load the children', async () => {
    /* The detail pane is still worth showing without them. */
    requestMock.mockImplementation((path: string) => {
      if (path.includes('/children')) return Promise.reject(new Error('nope'))
      if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
      if (path.includes('/collections')) return Promise.resolve({ collections: [] })
      if (path.includes('/tags')) return Promise.resolve({ tags: [] })
      return Promise.resolve({ total: 0, items: [] })
    })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.select(item('AAAA2345', 'One'))

    expect(store.selected?.key).toBe('AAAA2345')
    expect(store.failure).toBeNull()
  })

  it('builds a file URL for the library it is in', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()

    expect(store.fileUrl('AAAA2345')).toBe('/web/libraries/1/items/AAAA2345/file')
    expect(store.fileUrl('AAAA2345', { download: true })).toContain('download=true')
  })
})

describe('failures', () => {
  it('reports one rather than leaving the list blank', async () => {
    requestMock.mockImplementation((path: string) => {
      if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
      if (path.includes('/items?')) return Promise.reject(new Error('The server answered 500'))
      return Promise.resolve({ collections: [], tags: [], items: [] })
    })
    const store = useLibraryStore()

    await store.loadLibraries()

    expect(store.failure).toBe('The server answered 500')
  })
})
