import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { useLibraryStore } from './library'
import { useToastStore } from './toasts'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))
vi.mock('@/api/client', async (original) => ({
  ...(await original<typeof import('@/api/client')>()), request: requestMock,
}))

const inverse = { version: 11, items: [{ key: 'FIRST222', deleted: false }] }

beforeEach(() => {
  setActivePinia(createPinia())
  requestMock.mockReset()
  requestMock.mockImplementation((path: string, options?: { method?: string }) => {
    if (options?.method === 'PATCH') return Promise.resolve({ items: [], undo: inverse })
    if (options?.method === 'POST') return Promise.resolve({ items: [] })
    if (path.includes('/collections')) return Promise.resolve({ collections: [] })
    if (path.includes('/tags')) return Promise.resolve({ tags: [] })
    return Promise.resolve({ items: [], total: 0, libraryVersion: 11 })
  })
})

describe('undo offers for library errands', () => {
  it('undoes the server inverse at the original watermark, once', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    await library.trashItems(['FIRST222', 'SECOND22'])
    const toasts = useToastStore()
    expect(toasts.toasts[0]?.message).toBe('Items moved to trash.')
    expect(toasts.toasts[0]?.action?.label).toBe('Undo')
    const id = toasts.toasts[0]!.id
    await toasts.act(id)
    await toasts.act(id)
    expect(requestMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toEqual([
      ['/web/libraries/1/items/undo', {
        method: 'POST', headers: { 'If-Unmodified-Since-Version': '11' },
        body: { items: inverse.items },
      }],
    ])
    expect(toasts.toasts.at(-1)?.message).toBe('Change undone.')
  })

  it('keeps the original library when the reader switches before undo', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    await library.trashItems(['FIRST222'])
    library.libraryId = 2
    requestMock.mockClear()
    await useToastStore().act(useToastStore().toasts[0]!.id)
    expect(requestMock.mock.calls.map(([path]) => path)).toEqual(['/web/libraries/1/items/undo'])
  })

  it('keeps the original library when switching while the write is in flight', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    let finish!: (value: unknown) => void
    requestMock.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const write = library.trashItems(['FIRST222'])
    library.libraryId = 2
    finish({ items: [], undo: inverse })
    await write
    requestMock.mockClear()
    await useToastStore().act(useToastStore().toasts[0]!.id)
    expect(requestMock.mock.calls[0]?.[0]).toBe('/web/libraries/1/items/undo')
  })

  it('undoes the stored memberships, not the inverse of the requested delta', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    const items = [{ key: 'FIRST222', collections: ['ORIGINAL'] }]
    requestMock.mockResolvedValueOnce({ items: [], undo: { version: 11, items } })
    await library.fileItems(['FIRST222', 'SECOND22'], { add: ['NEWCOL22'], remove: ['ORIGINAL'] })
    expect(useToastStore().toasts[0]?.message).toBe('Items filed.')
    await useToastStore().act(useToastStore().toasts[0]!.id)
    expect(requestMock).toHaveBeenCalledWith('/web/libraries/1/items/undo', {
      method: 'POST', headers: { 'If-Unmodified-Since-Version': '11' }, body: { items },
    })
  })

  it('also confirms restoring items', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    await library.trashItems(['FIRST222'], false)
    expect(useToastStore().toasts[0]?.message).toBe('Items restored.')
  })

  it('reloads the open parents children after undoing a child trash', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    const parent = { key: 'PARENT22', version: 1, data: { itemType: 'book' }, meta: {} }
    const child = { key: 'FIRST222', version: 12, data: { itemType: 'note', parentItem: 'PARENT22' }, meta: {} }
    await library.trashItems(['FIRST222'])
    library.selected = parent
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return Promise.resolve({ items: [] })
      if (path.includes('/children')) return Promise.resolve({ items: [child] })
      if (path.includes('/items/PARENT22')) return Promise.resolve(parent)
      if (path.includes('/collections')) return Promise.resolve({ collections: [] })
      return Promise.resolve({ items: [parent], total: 1, libraryVersion: 12 })
    })
    await useToastStore().act(useToastStore().toasts[0]!.id)
    expect(library.children).toEqual([child])
  })

  it('does not offer an undo for a no-op or a refused write', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    requestMock.mockResolvedValueOnce({ items: [], undo: { version: 11, items: [] } })
    await library.trashItems(['FIRST222'])
    expect(useToastStore().toasts).toHaveLength(0)
    requestMock.mockRejectedValueOnce(new ApiError('Refused', 403))
    await expect(library.trashItems(['FIRST222'])).rejects.toMatchObject({ status: 403 })
    expect(useToastStore().toasts).toHaveLength(0)
  })

  it('keeps the undo offer when the write commits but refreshing fails', async () => {
    const library = useLibraryStore()
    library.libraryId = 1
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PATCH') return Promise.resolve({ items: [], undo: inverse })
      return Promise.reject(new Error(`Cannot refresh ${path}`))
    })
    await expect(library.trashItems(['FIRST222'])).resolves.toBeUndefined()
    expect(useToastStore().toasts[0]?.action?.label).toBe('Undo')
  })

  it.each([412, 403, 0])('reports a refused undo (%i) without retry or unhandled rejection', async (status) => {
    const library = useLibraryStore()
    library.libraryId = 1
    await library.trashItems(['FIRST222'])
    requestMock.mockRejectedValueOnce(new ApiError('Refused', status))
    await expect(useToastStore().act(useToastStore().toasts[0]!.id)).resolves.toBeUndefined()
    const message = status === 412
      ? 'Undo is no longer available because the library changed.' : 'Could not undo the change.'
    expect(useToastStore().toasts.at(-1)?.message).toBe(message)
    expect(requestMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
    expect(useToastStore().toasts.at(-1)?.action).toBeUndefined()
  })
})
