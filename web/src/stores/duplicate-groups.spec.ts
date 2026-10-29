import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useLibraryStore, type ItemEnvelope } from './library'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))
vi.mock('@/api/client', async (original) => ({
  ...(await original<typeof import('@/api/client')>()), request: requestMock,
}))
const row = (key: string): ItemEnvelope => ({ key, version: 1, data: { itemType: 'book', title: key }, meta: {} })
const groups = [['AAAA2345', 'BBBB2345'], ['CCCC2345', 'DDDD2345', 'EEEE2345']]
const rows = groups.flat().map(row)

beforeEach(() => {
  setActivePinia(createPinia())
  requestMock.mockReset()
  requestMock.mockResolvedValue({ items: rows, groups, total: 5, totalGroups: 2, libraryVersion: 7 })
})

describe('duplicate group selection', () => {
  it('opens the complete group from any member and replaces it on the next group', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    store.scope = 'duplicates'
    await store.loadItems()
    expect(requestMock.mock.calls[0]![0]).toContain('grouped=true')
    await store.select(rows[1]!)
    expect(store.selection).toEqual(groups[0])
    expect(store.selected).toBeNull()
    await store.select(rows[3]!)
    expect(store.selection).toEqual(groups[1])
    await store.selectAll()
    expect(store.selection).toEqual(groups[1])
  })

  it('can inspect one item explicitly and refine a selection within its group', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    store.scope = 'duplicates'
    await store.loadItems()
    await store.select(rows[0]!)
    await store.toggleSelected(rows[0]!)
    expect(store.selection).toEqual([rows[1]!.key])
    await store.toggleSelected(rows[3]!)
    expect(store.selection).toEqual(groups[1])
    requestMock.mockResolvedValueOnce(rows[3]).mockResolvedValueOnce({ items: [] })
    await store.inspectItem(rows[3]!)
    expect(store.selected?.key).toBe(rows[3]!.key)
  })

  it('pages by group count even when the first page holds more than 50 items', async () => {
    const many = Array.from({ length: 51 }, (_, i) => [row(`A${i}`), row(`B${i}`)])
    const store = useLibraryStore()
    store.libraryId = 1
    store.scope = 'duplicates'
    const page = (slice: ItemEnvelope[][]) => ({ items: slice.flat(), groups: slice.map((group) => group.map((item) => item.key)), total: 102, totalGroups: 51, libraryVersion: 7 })
    requestMock.mockResolvedValueOnce(page(many.slice(0, 50)))
    await store.loadItems()
    expect(store.hasMore).toBe(true)
    requestMock.mockResolvedValueOnce(page(many.slice(50)))
    await store.loadMore()
    expect(requestMock.mock.calls[1]![0]).toContain('start=50')
    expect(store.duplicateGroups).toHaveLength(51)
    expect(store.items).toHaveLength(102)
    expect(store.hasMore).toBe(false)
  })

  it('restarts pagination when the group watermark changes between pages', async () => {
    const store = useLibraryStore()
    store.libraryId = 1
    store.scope = 'duplicates'
    requestMock.mockResolvedValueOnce({ items: rows.slice(0, 2), groups: groups.slice(0, 1), total: 5, totalGroups: 2, libraryVersion: 7 })
    await store.loadItems()
    requestMock.mockResolvedValueOnce({ items: [], groups: [], total: 2, totalGroups: 1, libraryVersion: 8 })
    requestMock.mockResolvedValueOnce({ items: rows.slice(0, 2), groups: groups.slice(0, 1), total: 2, totalGroups: 1, libraryVersion: 8 })
    await store.loadMore()
    expect(requestMock.mock.calls[2]![0]).toContain('start=0')
    expect(store.duplicateGroups).toEqual(groups.slice(0, 1))
    expect(store.items).toHaveLength(2)
    expect(store.hasMore).toBe(false)
  })
})
