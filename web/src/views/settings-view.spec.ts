import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '@/i18n'

import SettingsView from './SettingsView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const ACCOUNT = {
  user: {
    id: 1,
    username: 'ada',
    displayName: 'Ada',
    email: 'ada@example.org',
    emailVerified: true,
    language: null,
    timeZone: null,
  },
  totpEnabled: false,
  sessions: [
    { id: 1, userAgent: 'Firefox', created: '2026-01-01T00:00:00Z', lastSeen: '2026-01-02T00:00:00Z', current: true },
  ],
}

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en'
  requestMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/account') return Promise.resolve(ACCOUNT)
    if (path === '/web/account/keys') return Promise.resolve({ keys: [] })
    if (path === '/web/account/locales') return Promise.resolve({ languages: [], timeZones: [] })
    return Promise.resolve({})
  })
})

/** Mount the screen at one section, through a router as the app has one. */
async function open(section = '') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings/:section?', name: 'settings', component: SettingsView }],
  })
  await router.push(section ? `/settings/${section}` : '/settings')
  await router.isReady()

  const wrapper = mount(SettingsView, { global: { plugins: [router] } })
  await settle(wrapper)
  return { wrapper, router }
}

/** Let the requests in flight answer, and the answers reach the screen. */
async function settle(wrapper: ReturnType<typeof mount>) {
  for (let round = 0; round < 4; round += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()
  }
}

describe('the settings panel', () => {
  it('lists every section', async () => {
    const { wrapper } = await open()

    expect(wrapper.findAll('.settings__section')).toHaveLength(4)
  })

  it('shows one section at a time, not the whole of settings', async () => {
    /* The point of the split: settings was one page long enough to scroll
       past the authenticator to reach the time zone. */
    const { wrapper } = await open()

    expect(wrapper.text()).toContain('Display name')
    expect(wrapper.text()).not.toContain('Authenticator app')
    expect(wrapper.text()).not.toContain('Time zone')
  })

  it('opens the section the URL names', async () => {
    const { wrapper } = await open('security')

    expect(wrapper.text()).toContain('Authenticator app')
    expect(wrapper.text()).not.toContain('Display name')
  })

  it('falls back to the first section when the URL names one that is gone', async () => {
    /* Settings is reached from a header icon; landing on an empty page there
       leaves no way to tell a stale link from a broken build. */
    const { wrapper } = await open('telepathy')

    expect(wrapper.text()).toContain('Display name')
    expect(wrapper.get('.settings__section--current').text()).toBe('Profile')
  })

  it('moves to another section when its row is clicked', async () => {
    const { wrapper, router } = await open()

    await wrapper.findAll('.settings__section')[3].trigger('click')
    await settle(wrapper)

    expect(router.currentRoute.value.params.section).toBe('keys')
    expect(wrapper.text()).toContain('What the Zotero app and any scripts use to sync')
  })

  it('does not ask the server for keys until the keys section is open', async () => {
    const { wrapper } = await open()

    expect(requestMock).not.toHaveBeenCalledWith('/web/account/keys')

    await wrapper.findAll('.settings__section')[3].trigger('click')
    await settle(wrapper)

    expect(requestMock).toHaveBeenCalledWith('/web/account/keys')
  })
})
