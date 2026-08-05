import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useLibraryStore } from './library'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const LIBRARIES = [
  { id: 1, type: 'user', ownerId: 1, name: 'Ada', version: 4, prefix: '/users/1', writable: true },
  {
    id: 2,
    type: 'group',
    ownerId: 100,
    name: 'Analytical Engine',
    version: 9,
    prefix: '/groups/100',
    writable: false,
  },
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

describe('collections', () => {
  /** The calls that changed something, as [path, options] pairs. */
  function writes(): [string, { method?: string; body?: unknown }][] {
    return requestMock.mock.calls.filter(
      ([, options]) => options && options.method && options.method !== 'GET',
    ) as [string, { method?: string; body?: unknown }][]
  }

  it('says whether the library it has open may be changed', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()
    expect(store.writable).toBe(true)

    await store.openLibrary(2)

    expect(store.writable).toBe(false)
  })

  it('posts a new collection to the library that is open', async () => {
    respond({ '/collections': { collections: [] } })
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return Promise.resolve(collection('DDDD2345', 'Papers'))
      if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
      if (path.includes('/collections')) return Promise.resolve({ collections: [] })
      if (path.includes('/tags')) return Promise.resolve({ tags: [] })
      return Promise.resolve({ total: 0, items: [] })
    })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.createCollection('Papers')

    expect(writes()).toEqual([
      ['/web/libraries/1/collections', { method: 'POST', body: { name: 'Papers' } }],
    ])
  })

  it('names the parent when one was given', async () => {
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return Promise.resolve(collection('DDDD2345', 'Drafts'))
      if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
      if (path.includes('/collections')) return Promise.resolve({ collections: [] })
      if (path.includes('/tags')) return Promise.resolve({ tags: [] })
      return Promise.resolve({ total: 0, items: [] })
    })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.createCollection('Drafts', 'CCCC2345')

    expect(writes()[0][1].body).toEqual({ name: 'Drafts', parentCollection: 'CCCC2345' })
  })

  it('opens what it just made, as the desktop client does', async () => {
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return Promise.resolve(collection('DDDD2345', 'Papers'))
      if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
      if (path.includes('/collections')) {
        return Promise.resolve({ collections: [collection('DDDD2345', 'Papers')] })
      }
      if (path.includes('/tags')) return Promise.resolve({ tags: [] })
      return Promise.resolve({ total: 0, items: [] })
    })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.createCollection('Papers')

    expect(store.collectionKey).toBe('DDDD2345')
    expect(store.collectionName).toBe('Papers')
  })

  it('deletes one by key', async () => {
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.deleteCollection('CCCC2345')

    expect(writes()).toEqual([['/web/libraries/1/collections/CCCC2345', { method: 'DELETE' }]])
  })

  it('falls back to the whole library when the open collection goes', async () => {
    /* The key is gone from the server; leaving it selected would list nothing
       and report that the collection is empty. */
    respond({ '/collections': { collections: [collection('CCCC2345', 'Papers')] } })
    const store = useLibraryStore()
    await store.loadLibraries()
    await store.selectCollection('CCCC2345')

    await store.deleteCollection('CCCC2345')

    expect(store.collectionKey).toBeNull()
  })

  it('leaves a different open collection alone', async () => {
    respond({
      '/collections': {
        collections: [collection('CCCC2345', 'Papers'), collection('DDDD2345', 'Books')],
      },
    })
    const store = useLibraryStore()
    await store.loadLibraries()
    await store.selectCollection('CCCC2345')

    await store.deleteCollection('DDDD2345')

    expect(store.collectionKey).toBe('CCCC2345')
  })

  it('lets a failure through rather than swallowing it', async () => {
    /* The view puts the message beside the control that was used. A store that
       reported success here would leave a collection that was never made. */
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return Promise.reject(new Error('The server answered 403'))
      if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
      if (path.includes('/collections')) return Promise.resolve({ collections: [] })
      if (path.includes('/tags')) return Promise.resolve({ tags: [] })
      return Promise.resolve({ total: 0, items: [] })
    })
    const store = useLibraryStore()
    await store.loadLibraries()

    await expect(store.createCollection('Papers')).rejects.toThrow('The server answered 403')
  })
})

describe('where a collection is', () => {
  const TREE = [
    collection('CCCC2345', 'Whales'),
    collection('DDDD2345', 'Humpbacks', 'CCCC2345'),
    collection('EEEE2345', 'Blue', 'DDDD2345'),
    collection('FFFF2345', 'Dolphins'),
  ]

  it('gives the path from the top down to a nested collection', async () => {
    respond({ '/collections': { collections: TREE } })
    const store = useLibraryStore()
    await store.loadLibraries()

    expect(store.pathTo('EEEE2345').map((node) => node.data.name)).toEqual([
      'Whales',
      'Humpbacks',
      'Blue',
    ])
  })

  it('gives a top-level collection a path of one', async () => {
    respond({ '/collections': { collections: TREE } })
    const store = useLibraryStore()
    await store.loadLibraries()

    expect(store.pathTo('FFFF2345').map((node) => node.data.name)).toEqual(['Dolphins'])
  })

  it('gives nothing for a collection the tree does not hold', async () => {
    /* A shorter path rather than a wrong one: the key may have just gone. */
    respond({ '/collections': { collections: TREE } })
    const store = useLibraryStore()
    await store.loadLibraries()

    expect(store.pathTo('ZZZZ9999')).toEqual([])
    expect(store.pathTo(null)).toEqual([])
  })

  it('names the collection the sidebar has open', async () => {
    respond({ '/collections': { collections: TREE } })
    const store = useLibraryStore()
    await store.loadLibraries()

    await store.selectCollection('DDDD2345')

    expect(store.selectedCollection?.key).toBe('DDDD2345')
    expect(store.collectionName).toBe('Humpbacks')
  })

  it('has none open when the sidebar is on the library itself', async () => {
    respond({ '/collections': { collections: TREE } })
    const store = useLibraryStore()
    await store.loadLibraries()

    expect(store.selectedCollection).toBeNull()
  })
})
