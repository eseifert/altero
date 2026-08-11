import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { useShareStore, type CollectionShare } from './shares'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const SHARE: CollectionShare = {
  id: 7,
  collection: 'ABCD2345',
  collectionName: 'Papers',
  subcollections: true,
  files: true,
  created: '2026-08-01T00:00:00Z',
  expires: null,
  lastUsed: null,
  createdBy: 1,
}

describe('the share store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  it('lists the links out of one library', async () => {
    requestMock.mockResolvedValue({ shares: [SHARE] })
    const store = useShareStore()

    await store.load(2)

    expect(requestMock).toHaveBeenCalledWith('/web/libraries/2/shares')
    expect(store.shares).toEqual([SHARE])
  })

  it('holds the link a fresh share carries, which is the only time it is sent', async () => {
    requestMock
      .mockResolvedValueOnce({ ...SHARE, url: 'http://here/app/shared/tok' })
      .mockResolvedValueOnce({ shares: [SHARE] })
    const store = useShareStore()

    await store.create(2, 'ABCD2345', { subcollections: true, files: false, expires: null })

    expect(requestMock.mock.calls[0]).toEqual([
      '/web/libraries/2/collections/ABCD2345/shares',
      { method: 'POST', body: { subcollections: true, files: false, expires: null } },
    ])
    expect(store.issued?.url).toBe('http://here/app/shared/tok')
    /* And the list it reloads does not carry it, because the server sends it
       exactly once. */
    expect(store.shares[0].url).toBeUndefined()
  })

  it('forgets the issued link when it is revoked', async () => {
    requestMock
      .mockResolvedValueOnce({ ...SHARE, url: 'http://here/app/shared/tok' })
      .mockResolvedValueOnce({ shares: [SHARE] })
    const store = useShareStore()
    await store.create(2, 'ABCD2345', { subcollections: true, files: true, expires: null })

    requestMock.mockResolvedValueOnce(undefined).mockResolvedValueOnce({ shares: [] })
    await store.revoke(2, SHARE.id)

    expect(store.issued).toBeNull()
    expect(store.shares).toEqual([])
  })

  it('reports a refusal rather than throwing it', async () => {
    requestMock.mockRejectedValue(new ApiError('You cannot share from this library', 403))
    const store = useShareStore()

    await store.create(2, 'ABCD2345', { subcollections: true, files: true, expires: null })

    expect(store.error).toBe('You cannot share from this library')
    expect(store.issued).toBeNull()
  })
})
