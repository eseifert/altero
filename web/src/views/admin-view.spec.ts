import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

import AdminView from './AdminView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const OVERVIEW = {
  version: '0.9.0',
  apiVersion: 3,
  revision: '807916070e0e',
  database: 'sqlite',
  users: 3,
  libraries: 4,
  groups: 1,
  storagePath: '/var/lib/altero/storage',
  nominalBytes: 3_000_000,
  realBytes: 2_000_000,
  savedBytes: 1_000_000,
  orphanFiles: 0,
  missingFiles: 0,
}

const STORAGE = {
  libraries: [
    {
      id: 1,
      type: 'user',
      ownerId: 1,
      name: 'Ada',
      version: 12,
      items: 40,
      trashed: 2,
      collections: 3,
      tags: 8,
      attachments: 5,
      files: 5,
      bytes: 2_000_000,
      missing: 0,
    },
  ],
  nominalBytes: 3_000_000,
  realBytes: 2_000_000,
  savedBytes: 1_000_000,
  storedFiles: 5,
  storedBytes: 2_000_000,
  orphanFiles: 2,
  orphanBytes: 500_000,
  missingFiles: 0,
}

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en'
  requestMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/admin/overview') return Promise.resolve(OVERVIEW)
    if (path === '/web/admin/storage') return Promise.resolve(STORAGE)
    return Promise.resolve({})
  })
})

/** Let every pending promise settle, including the ones they start. */
async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve))
  await new Promise((resolve) => setTimeout(resolve))
}

async function open(section = '') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/admin/:section?', name: 'admin', component: AdminView },
      { path: '/library', name: 'library', component: { template: '<div />' } },
    ],
  })
  await router.push(section ? `/admin/${section}` : '/admin')
  await router.isReady()

  const wrapper = mount(AdminView, {
    global: { plugins: [i18n, router] },
  })
  await flush()
  return wrapper
}

describe('the administration screens', () => {
  it('opens on the overview', async () => {
    const wrapper = await open()

    expect(wrapper.get('.section-panel__section--current').text()).toBe('Overview')
  })

  it('reports what the instance is running', async () => {
    const wrapper = await open()

    expect(wrapper.text()).toContain('0.9.0')
    expect(wrapper.text()).toContain('807916070e0e')
    expect(wrapper.text()).toContain('/var/lib/altero/storage')
  })

  it('says so when the database was never stamped with a revision', async () => {
    requestMock.mockImplementation(() => Promise.resolve({ ...OVERVIEW, revision: null }))

    const wrapper = await open()

    expect(wrapper.text()).toContain('not stamped')
  })

  it('lists each library with what it holds', async () => {
    const wrapper = await open('storage')

    const row = wrapper.get('tbody tr')
    expect(row.text()).toContain('Ada')
    expect(row.text()).toContain('user/1')
    expect(row.text()).toContain('40')
  })

  it('writes bytes in units a person reads', async () => {
    const wrapper = await open('storage')

    expect(wrapper.text()).toContain('2 MB')
  })

  it('says what deduplication has saved', async () => {
    /* The number zotero.org cannot report: a file in two libraries is on disk
       once. Hiding it would make the two totals look like a contradiction. */
    const wrapper = await open('storage')

    expect(wrapper.text()).toContain('Saved by storing each file once')
    expect(wrapper.text()).toContain('1 MB')
  })

  it('reports files no library references any more', async () => {
    const wrapper = await open('storage')

    expect(wrapper.text()).toContain('no longer referenced')
  })

  it('does not fetch a section that is not showing', async () => {
    await open()

    expect(requestMock).not.toHaveBeenCalledWith('/web/admin/storage')
  })
})

describe('who may reach the screens', () => {
  /** The application's own router, guard and all. */
  async function reach(administrator: boolean): Promise<string> {
    const { router } = await import('@/router')
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      username: 'ada',
      displayName: 'Ada',
      email: null,
      emailVerified: false,
      language: null,
      timeZone: null,
      profileVisibility: 'public',
      administrator,
    }
    // Already checked, so the guard does not go and ask the server.
    auth.ready = true

    // The router module is one object across this file, so a second push to
    // the path it is already on would be a duplicate and run no guard at all.
    await router.push('/library')
    await router.push('/admin/overview')
    await router.isReady()
    return router.currentRoute.value.path
  }

  it('lets an administrator in', async () => {
    expect(await reach(true)).toBe('/admin/overview')
  })

  it('turns an ordinary account back to their library', async () => {
    /* Not to the sign-in form: they are signed in, and signing in again would
       not help. The server refuses these routes regardless. */
    expect(await reach(false)).toBe('/library')
  })
})
