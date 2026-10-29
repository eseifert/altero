import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { useLibraryStore, type ItemEnvelope } from './library'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))
vi.mock('@/api/client', async (original) => ({
  ...(await original<typeof import('@/api/client')>()), request: requestMock,
}))
const item = (key: string): ItemEnvelope => ({ key, version: 1, data: { itemType: 'book' }, meta: {} })
const rows = [item('MASTER22'), item('DUPL2345')]

beforeEach(() => {
  setActivePinia(createPinia())
  requestMock.mockReset()
  requestMock.mockImplementation((path: string, options?: { method?: string }) => {
    if (options?.method === 'POST') return Promise.resolve({ items: [{ ...rows[0], version: 18 }] })
    if (path.includes('itemKey=')) return Promise.resolve({ items: rows, total: 2, libraryVersion: 17 })
    if (path.includes('/collections')) return Promise.resolve({ collections: [] })
    if (path.includes('/tags')) return Promise.resolve({ tags: [] })
    return Promise.resolve({ items: [], total: 0, libraryVersion: 88 })
  })
})

describe('a reviewed merge snapshot', () => {
  it('reads the selected items independently of list filters', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    store.search = 'old search'
    store.scope = 'duplicates'
    store.collectionKey = 'COLL2345'
    const snapshot = await store.prepareMerge(rows.map((row) => row.key))
    const path = requestMock.mock.calls[0]![0] as string
    expect(path).toContain('scope=all')
    expect(path).not.toContain('old+search')
    expect(path).not.toContain('collection=')
    expect(snapshot.version).toBe(17)
    expect(snapshot.items.map((row) => row.key)).toEqual(rows.map((row) => row.key))
  })

  it('uses the review version even after another read advances the page', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    const snapshot = await store.prepareMerge(rows.map((row) => row.key))
    await store.loadItems()
    await store.mergeItems(snapshot, 'MASTER22', { title: 'Chosen' }, 'de')
    expect(requestMock).toHaveBeenCalledWith('/web/libraries/1/items/merge?locale=de', {
      method: 'POST', headers: { 'If-Unmodified-Since-Version': '17' },
      body: { master: 'MASTER22', others: ['DUPL2345'], fields: { title: 'Chosen' } },
    })
  })

  it('does not retry or replace the choices after a 412', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    const snapshot = await store.prepareMerge(rows.map((row) => row.key))
    requestMock.mockRejectedValueOnce(new ApiError('Changed', 412))
    await expect(store.mergeItems(snapshot, 'MASTER22', {}, 'en-US')).rejects.toMatchObject({ status: 412 })
    expect(requestMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
    expect(snapshot.version).toBe(17)
  })

  it('rejects a snapshot with missing selected items', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    requestMock.mockResolvedValueOnce({ items: rows.slice(0, 1), total: 1, libraryVersion: 17 })
    await expect(store.prepareMerge(rows.map((row) => row.key))).rejects.toMatchObject({ status: 412 })
  })

  it('requires all batches to come from one library version', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    const many = Array.from({ length: 101 }, (_, i) => item(String(i).padStart(8, 'A')))
    requestMock.mockResolvedValueOnce({ items: many.slice(0, 100), total: 100, libraryVersion: 17 })
    requestMock.mockResolvedValueOnce({ items: many.slice(100), total: 1, libraryVersion: 18 })
    await expect(store.prepareMerge(many.map((row) => row.key))).rejects.toMatchObject({ status: 412 })
  })

  it('keeps a committed success when a subsequent refresh fails', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    const snapshot = await store.prepareMerge(rows.map((row) => row.key))
    requestMock.mockImplementation((_path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return Promise.resolve({ items: [{ ...rows[0], version: 18 }] })
      return Promise.reject(new ApiError('Offline', 0))
    })
    await expect(store.mergeItems(snapshot, 'MASTER22', {}, 'en-US')).resolves.toBeUndefined()
    expect(store.failure).toBe('Offline')
  })

  it('does not clear a new library selection when an older merge finishes', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    const snapshot = await store.prepareMerge(rows.map((row) => row.key))
    let finish!: (value: unknown) => void
    requestMock.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const pending = store.mergeItems(snapshot, 'MASTER22', {}, 'en-US')
    store.libraryId = 2
    store.selection = ['OTHER234']
    finish({ items: [{ ...rows[0], version: 18 }] })
    await pending
    expect(store.selection).toEqual(['OTHER234'])
  })
})
