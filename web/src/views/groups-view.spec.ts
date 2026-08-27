import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import type { Group } from '@/stores/groups'

import GroupsView from './GroupsView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const ADA = {
  id: 1,
  username: 'ada',
  displayName: 'Ada',
  email: 'ada@example.org',
  emailVerified: true,
  language: null,
  timeZone: null,
  profileVisibility: 'public' as const,
  administrator: false,
}

const GRACE = {
  id: 2,
  username: 'grace',
  displayName: 'Grace',
  role: 'member',
  permission: 'inherit',
  owner: false,
}

function group(overrides: Partial<Group> = {}): Group {
  return {
    id: 2,
    groupId: 1,
    name: 'Analytical Engine',
    description: 'Notes and papers',
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
    ...overrides,
  }
}

function detail(overrides: Partial<Group> = {}) {
  return {
    ...group(overrides),
    members: [
      { id: 1, username: 'ada', displayName: 'Ada', role: 'admin', owner: true },
      GRACE,
    ],
    invitations: [{ id: 9, email: 'hopper@example.org', role: 'member', expires: '2026-09-01T00:00:00Z' }],
    notifications: {
      itemsChanged: false,
      itemsDeleted: false,
      membersChanged: false,
      collectionsChanged: false,
    },
  }
}

const activity = {
  activity: [
    {
      id: 2,
      kind: 'items_deleted',
      count: 1,
      when: '2026-08-05T10:00:00Z',
      actor: { id: 2, username: 'grace', name: 'Grace' },
      objects: [{ key: 'AAAA2345', name: 'Moby-Dick' }],
    },
    {
      id: 1,
      kind: 'items_changed',
      count: 4,
      when: '2026-08-05T09:00:00Z',
      actor: null,
      objects: [
        { key: 'BBBB2345', name: 'Omoo' },
        { key: 'CCCC2345', name: 'Typee' },
        { key: 'DDDD2345', name: '' },
        { key: 'EEEE2345', name: 'Redburn' },
      ],
    },
  ],
  total: 2,
}

/** Mount the screen with `who` signed in and `list` as their groups. */
async function screen(list: Group[] = [group()], who = ADA) {
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/groups') return Promise.resolve({ groups: list })
    if (path.includes('/activity')) return Promise.resolve(activity)
    if (path.startsWith('/web/groups/')) return Promise.resolve(detail(list[0]))
    return Promise.resolve({})
  })

  const wrapper = mount(GroupsView, { global: { plugins: [i18n], stubs: { RouterLink: true } } })
  useAuthStore().user = who
  await flush()
  return wrapper
}

/** Let every pending promise settle, including the ones they start. */
async function flush(): Promise<void> {
  for (let round = 0; round < 6; round += 1) {
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en-US'
  requestMock.mockReset()
})

describe('the groups screen', () => {
  it('lists the groups with what this account may do in each', async () => {
    const wrapper = await screen()

    expect(wrapper.text()).toContain('Analytical Engine')
    expect(wrapper.text()).toContain('2 members')
    expect(wrapper.text()).toContain('Administrator')
  })

  it('says so when there are none', async () => {
    const wrapper = await screen([])

    expect(wrapper.text()).toContain('You are not in any groups yet.')
  })

  it('shows the members once a group is opened', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('Grace')
    expect(wrapper.text()).toContain('Owner')
  })

  it('offers an administrator the policy controls', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('Who may do what')
    expect(wrapper.findAll('select').length).toBeGreaterThan(3)
  })

  it('offers a plain member none of them', async () => {
    /* The server refuses either way; drawing a control that will be refused
       is a promise the screen cannot keep. */
    const wrapper = await screen([group({ role: 'member', owner: false, ownerId: 2 })])

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).not.toContain('Who may do what')
    expect(wrapper.text()).not.toContain('Delete this group')
  })

  it('asks before deleting a group', async () => {
    /* Deleting takes a library with it and there is no trash around one, so
       the button must not be the last thing between a click and that. */
    const wrapper = await screen()
    await wrapper.find('.card').trigger('click')
    await flush()

    const remove = wrapper.findAll('button').find((button) => button.text() === 'Delete')
    await remove?.trigger('click')

    expect(wrapper.text()).toContain('Delete “Analytical Engine” and everything in it?')
    expect(requestMock.mock.calls.filter(([, options]) => options?.method === 'DELETE')).toEqual([])
  })

  it('lists the invitations an administrator has sent', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('hopper@example.org')
    expect(wrapper.text()).toContain('Withdraw')
  })

  it('creates a group from the form', async () => {
    const wrapper = await screen([])

    await wrapper.findAll('button').find((button) => button.text() === 'New group')?.trigger('click')
    await wrapper.find('input').setValue('Difference Engine')
    await wrapper.find('form').trigger('submit')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/groups', {
      method: 'POST',
      body: { name: 'Difference Engine', description: '' },
    })
  })

  it('offers a notification toggle for each kind of change', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('Tell me about')
    expect(wrapper.findAll('.notify input[type="checkbox"]')).toHaveLength(4)
  })

  it('starts with every toggle off, because nothing is subscribed by default', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    const boxes = wrapper.findAll('.notify input[type="checkbox"]')
    expect(boxes.every((box) => !(box.element as HTMLInputElement).checked)).toBe(true)
  })

  it('sends only the toggle that was changed', async () => {
    const wrapper = await screen()
    await wrapper.find('.card').trigger('click')
    await flush()

    requestMock.mockClear()
    await wrapper.find('.notify input[type="checkbox"]').setValue(true)
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/groups/2/notifications', {
      method: 'PUT',
      body: { itemsChanged: true },
    })
  })

  it('says where the notifications go', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('ada@example.org')
  })

  it('shows what has happened in the group', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('Recent activity')
    expect(wrapper.findAll('.activity__entry')).toHaveLength(2)
  })

  it('names who did it, and says so when nobody can be named', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    const entries = wrapper.findAll('.activity__entry')
    expect(entries[0].text()).toContain('Grace')
    expect(entries[1].text()).toContain('Somebody')
  })

  it('counts what each change touched', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    const entries = wrapper.findAll('.activity__entry')
    expect(entries[0].text()).toContain('1 item')
    expect(entries[1].text()).toContain('4 items')
  })

  it('says so when nothing has happened', async () => {
    requestMock.mockImplementation((path: string) => {
      if (path === '/web/groups') return Promise.resolve({ groups: [group()] })
      if (path.includes('/activity')) return Promise.resolve({ activity: [], total: 0 })
      if (path.startsWith('/web/groups/')) return Promise.resolve(detail(group()))
      return Promise.resolve({})
    })
    const wrapper = mount(GroupsView, {
      global: { plugins: [i18n], stubs: { RouterLink: true } },
    })
    useAuthStore().user = ADA
    await flush()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('Nothing has happened here yet.')
  })

  it('names what each change touched', async () => {
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('Moby-Dick')
    expect(wrapper.text()).toContain('Omoo')
  })

  it('falls back to a placeholder for something that had no name', async () => {
    // A note saved empty, or an item whose title field was never filled in.
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('(untitled)')
  })

  it('does not list every object in a large change', async () => {
    // Fifty titles under one line would bury the log. The count already says
    // how many; the names are there to recognise a change, not to enumerate it.
    const wrapper = await screen()

    await wrapper.find('.card').trigger('click')
    await flush()

    const second = wrapper.findAll('.activity__entry')[1]
    expect(second.findAll('.activity__object')).toHaveLength(3)
    expect(second.text()).toContain('1 more')
  })
})
