import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { useNotificationStore } from './notifications'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const INVITATION = {
  id: 7,
  libraryId: 2,
  libraryName: 'Analytical Engine',
  role: 'member',
  invitedBy: 'Grace',
  status: 'pending',
  created: '2026-08-03T00:00:00Z',
  expires: '2026-08-17T00:00:00Z',
}

const NOTICE = {
  id: 1,
  kind: 'invitation',
  subject: 'Grace invited you to “Analytical Engine”',
  body: '',
  invitationId: 7,
  created: '2026-08-03T00:00:00Z',
  read: false,
}

/**
 * A fresh payload every time.
 *
 * The store mutates what it is handed -- markRead flips `read` in place -- so
 * returning the same objects makes one test's changes the next test's starting
 * state. That is how "does not lower the count twice" first failed: the entry
 * arrived already read, mutated by the test above it.
 */
function payload(overrides: Record<string, unknown> = {}) {
  return structuredClone({
    unread: 1,
    notifications: [NOTICE],
    invitations: [INVITATION],
    ...overrides,
  })
}

describe('the notification store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  it('loads notifications and invitations together', async () => {
    requestMock.mockResolvedValue(payload())
    const store = useNotificationStore()

    await store.load()

    expect(store.notifications).toHaveLength(1)
    expect(store.invitations).toHaveLength(1)
    expect(store.unread).toBe(1)
    expect(store.hasUnread).toBe(true)
  })

  it('does not take the page down when it cannot load', async () => {
    requestMock.mockRejectedValue(new ApiError('Could not reach the server', 0))
    const store = useNotificationStore()

    await store.load()

    expect(store.error).toBe('Could not reach the server')
    expect(store.notifications).toEqual([])
  })

  it('lowers the count when one is marked read', async () => {
    requestMock.mockResolvedValueOnce(payload({ unread: 2 }))
    const store = useNotificationStore()
    await store.load()

    requestMock.mockResolvedValueOnce(null)
    await store.markRead(1)

    expect(store.unread).toBe(1)
    expect(store.notifications[0].read).toBe(true)
  })

  it('does not lower the count twice for the same one', async () => {
    requestMock.mockResolvedValueOnce(payload({ unread: 1 }))
    const store = useNotificationStore()
    await store.load()

    requestMock.mockResolvedValue(null)
    await store.markRead(1)
    await store.markRead(1)

    expect(store.unread).toBe(0)
  })

  it('clears the count when all are marked read', async () => {
    requestMock.mockResolvedValueOnce(payload({ unread: 3 }))
    const store = useNotificationStore()
    await store.load()

    requestMock.mockResolvedValueOnce(null)
    await store.markAllRead()

    expect(store.unread).toBe(0)
    expect(store.notifications.every((entry) => entry.read)).toBe(true)
  })

  it('reloads after answering, because accepting changes more than one thing', async () => {
    requestMock.mockResolvedValueOnce(payload())
    const store = useNotificationStore()
    await store.load()

    requestMock.mockResolvedValueOnce(null)
    requestMock.mockResolvedValueOnce(payload({ unread: 0, notifications: [], invitations: [] }))
    await store.answer(7, 'accept')

    expect(requestMock).toHaveBeenCalledWith('/web/invitations/7/accept', { method: 'POST' })
    expect(store.invitations).toEqual([])
    expect(store.unread).toBe(0)
  })

  it('declines through its own endpoint', async () => {
    const store = useNotificationStore()
    requestMock.mockResolvedValueOnce(null)
    requestMock.mockResolvedValueOnce(payload({ unread: 0, notifications: [], invitations: [] }))

    await store.answer(7, 'decline')

    expect(requestMock).toHaveBeenCalledWith('/web/invitations/7/decline', { method: 'POST' })
  })

  it('surfaces why an invitation could not be answered', async () => {
    const store = useNotificationStore()
    requestMock.mockRejectedValueOnce(
      new ApiError('That invitation has already been answered', 403),
    )

    await expect(store.answer(7, 'accept')).rejects.toThrow()

    expect(store.error).toBe('That invitation has already been answered')
  })

  it('empties on sign-out, so the next person sees nothing of the last', async () => {
    requestMock.mockResolvedValue(payload())
    const store = useNotificationStore()
    await store.load()

    store.reset()

    expect(store.notifications).toEqual([])
    expect(store.invitations).toEqual([])
    expect(store.unread).toBe(0)
  })
})
