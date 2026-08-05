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
}

const GRACE = { id: 2, username: 'grace', displayName: 'Grace', role: 'member', owner: false }

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

/** Mount the screen with `who` signed in and `list` as their groups. */
async function screen(list: Group[] = [group()], who = ADA) {
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/groups') return Promise.resolve({ groups: list })
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
  i18n.global.locale.value = 'en'
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
})
