import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { useGroupStore, type Group } from './groups'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const GROUP: Group = {
  id: 2,
  groupId: 1,
  name: 'Analytical Engine',
  description: '',
  type: 'Private',
  libraryReading: 'members',
  libraryEditing: 'members',
  fileEditing: 'members',
  version: 3,
  role: 'admin',
  permission: 'inherit',
  owner: true,
  ownerId: 1,
  numMembers: 2,
  numItems: 10,
}

function payload(overrides: Partial<Group> = {}) {
  return structuredClone({ groups: [{ ...GROUP, ...overrides }] })
}

describe('the group store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  it('loads the groups this account belongs to', async () => {
    requestMock.mockResolvedValue(payload())
    const store = useGroupStore()

    await store.load()

    expect(store.groups).toHaveLength(1)
    expect(store.hasGroups).toBe(true)
    expect(store.error).toBeNull()
  })

  it('reports a failure rather than throwing', async () => {
    /* Every screen reads `error`; a store that threw would leave each caller
       to remember a try/catch, and one that forgot would take the page down. */
    requestMock.mockRejectedValue(new ApiError('Not signed in', 401))
    const store = useGroupStore()

    await store.load()

    expect(store.error).toBe('Not signed in')
    expect(store.groups).toEqual([])
  })

  it('reloads the list after creating one', async () => {
    requestMock.mockResolvedValueOnce(GROUP).mockResolvedValueOnce(payload())
    const store = useGroupStore()

    const created = await store.create({ name: 'Analytical Engine' }, 'Group created.')

    expect(created?.name).toBe('Analytical Engine')
    expect(store.notice).toBe('Group created.')
    expect(requestMock.mock.calls[0]).toEqual([
      '/web/groups',
      { method: 'POST', body: { name: 'Analytical Engine' } },
    ])
    expect(requestMock.mock.calls[1][0]).toBe('/web/groups')
  })

  it('does not reload after a refused creation', async () => {
    requestMock.mockRejectedValueOnce(new ApiError('A group name is required', 400))
    const store = useGroupStore()

    const created = await store.create({ name: '' }, 'Group created.')

    expect(created).toBeNull()
    expect(store.error).toBe('A group name is required')
    expect(requestMock).toHaveBeenCalledTimes(1)
  })

  it('clears the previous message before each attempt', async () => {
    /* A notice left over from the last thing that worked, sitting above the
       thing that just failed, reads as if the failure had succeeded. */
    requestMock.mockResolvedValueOnce(GROUP).mockResolvedValueOnce(payload())
    const store = useGroupStore()
    await store.create({ name: 'x' }, 'Group created.')

    requestMock.mockRejectedValueOnce(new ApiError('Only an administrator', 403))
    await store.update(2, { name: 'y' }, 'Group saved.')

    expect(store.notice).toBeNull()
    expect(store.error).toBe('Only an administrator')
  })

  it('changes a role without reloading the whole list', async () => {
    /* The panel refetches the one group it has open; reloading everything as
       well would be a second round trip for a screen already on its way. */
    requestMock.mockResolvedValue({})
    const store = useGroupStore()

    await store.setRole(2, 5, 'admin')

    expect(requestMock).toHaveBeenCalledTimes(1)
    expect(requestMock.mock.calls[0]).toEqual([
      '/web/groups/2/members/5',
      { method: 'PUT', body: { role: 'admin' } },
    ])
  })

  it('reloads after leaving or removing somebody', async () => {
    requestMock.mockResolvedValueOnce({}).mockResolvedValueOnce({ groups: [] })
    const store = useGroupStore()

    await store.removeMember(2, 5)

    expect(store.groups).toEqual([])
  })

  it('invites through the library the invitation belongs to', async () => {
    requestMock.mockResolvedValue({})
    const store = useGroupStore()

    await store.invite(2, 'ada@example.org', 'member', 'read', 'Invitation sent.')

    expect(requestMock.mock.calls[0]).toEqual([
      '/web/libraries/2/invitations',
      { method: 'POST', body: { email: 'ada@example.org', role: 'member', permission: 'read' } },
    ])
  })

  it('sends only the toggle that moved', async () => {
    requestMock.mockResolvedValue({
      itemsChanged: true,
      itemsDeleted: false,
      membersChanged: false,
      collectionsChanged: false,
    })
    const store = useGroupStore()

    await store.setNotification(2, 'itemsChanged', true)

    expect(requestMock.mock.calls[0]).toEqual([
      '/web/groups/2/notifications',
      { method: 'PUT', body: { itemsChanged: true } },
    ])
  })

  it('keeps the answered preferences on the group it holds', async () => {
    requestMock.mockResolvedValueOnce(payload())
    const store = useGroupStore()
    await store.load()

    requestMock.mockResolvedValueOnce({
      itemsChanged: true,
      itemsDeleted: false,
      membersChanged: false,
      collectionsChanged: false,
    })
    await store.setNotification(2, 'itemsChanged', true)

    expect(store.groups[0].notifications).toEqual({
      itemsChanged: true,
      itemsDeleted: false,
      membersChanged: false,
      collectionsChanged: false,
    })
  })

  it('reports a refusal rather than pretending the toggle moved', async () => {
    requestMock.mockRejectedValue(new ApiError('Forbidden', 403))
    const store = useGroupStore()

    await store.setNotification(2, 'itemsChanged', true)

    expect(store.error).toBeTruthy()
  })

  it('reads the activity log newest first', async () => {
    requestMock.mockResolvedValue({
      activity: [
        {
          id: 2,
          kind: 'items_deleted',
          count: 1,
          when: '2026-08-05T10:00:00Z',
          actor: null,
          objects: [{ key: 'AAAA2345', name: 'Moby-Dick' }],
        },
        {
          id: 1,
          kind: 'items_changed',
          count: 4,
          when: '2026-08-05T09:00:00Z',
          actor: { id: 1, username: 'ada', name: 'Ada' },
          objects: [],
        },
      ],
      total: 2,
    })
    const store = useGroupStore()

    const page = await store.readActivity(2)

    expect(requestMock.mock.calls[0][0]).toBe('/web/groups/2/activity')
    expect(page?.activity.map((entry) => entry.kind)).toEqual(['items_deleted', 'items_changed'])
    expect(page?.total).toBe(2)
    expect(page?.activity[0].objects).toEqual([{ key: 'AAAA2345', name: 'Moby-Dick' }])
  })

  it('reports a refusal to read the log rather than showing an empty one', async () => {
    requestMock.mockRejectedValue(new ApiError('No such group', 404))
    const store = useGroupStore()

    const page = await store.readActivity(2)

    expect(page).toBeNull()
    expect(store.error).toBeTruthy()
  })

  it('forgets everything on sign-out', async () => {
    requestMock.mockResolvedValue(payload())
    const store = useGroupStore()
    await store.load()

    store.reset()

    expect(store.groups).toEqual([])
    expect(store.hasGroups).toBe(false)
  })
})
