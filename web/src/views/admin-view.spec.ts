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

const SETTINGS = {
  settings: { trashRetentionDays: 0, activityRetentionDays: 0, uploadRetentionHours: 24 },
  defaults: { trashRetentionDays: 0, activityRetentionDays: 0, uploadRetentionHours: 24 },
  limits: {
    trashRetentionDays: { maximum: 3650, zero: 'never' },
    activityRetentionDays: { maximum: 3650, zero: 'never' },
    uploadRetentionHours: { maximum: 8760, zero: 'never' },
  },
}

const ACCOUNTS = [
  {
    id: 1,
    username: 'ada',
    displayName: 'Ada',
    email: 'ada@example.org',
    emailVerified: true,
    administrator: true,
    disabled: false,
    disabledAt: null,
    keys: 2,
    groups: 1,
  },
  {
    id: 2,
    username: 'grace',
    displayName: 'Grace',
    email: null,
    emailVerified: false,
    administrator: false,
    disabled: false,
    disabledAt: null,
    keys: 0,
    groups: 0,
  },
  {
    id: 3,
    username: 'rita',
    displayName: 'Rita',
    email: null,
    emailVerified: false,
    administrator: false,
    disabled: true,
    disabledAt: '2026-08-01T00:00:00Z',
    keys: 1,
    groups: 0,
  },
]

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en'
  requestMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/admin/overview') return Promise.resolve(OVERVIEW)
    if (path === '/web/admin/storage') return Promise.resolve(STORAGE)
    if (path === '/web/admin/settings') return Promise.resolve(SETTINGS)
    if (path === '/web/admin/users') return Promise.resolve({ users: ACCOUNTS })
    if (path.startsWith('/web/admin/retention/run')) {
      return Promise.resolve({
        preview: path.includes('preview=true'),
        itemsDeleted: 3,
        libraries: 1,
        activity: 0,
        uploads: 0,
        sessions: 0,
        verifications: 0,
        invitations: 0,
        summary: '3 items out of the trash in 1 libraries',
      })
    }
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

/** One button, by what it says: the order on the screen is not the contract. */
function button(wrapper: ReturnType<typeof mount>, label: string) {
  const found = wrapper.findAll('button').find((candidate) => candidate.text() === label)
  if (!found) throw new Error(`No button labelled "${label}"`)
  return found
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

  it('deletes them only when asked, and with the password', async () => {
    /* The one irreversible thing on these screens. */
    const wrapper = await open('storage')

    expect(button(wrapper, 'Delete unreferenced files').attributes('disabled')).toBeDefined()

    await wrapper.get('input[type="password"]').setValue('a good password')
    await button(wrapper, 'Delete unreferenced files').trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/admin/storage/purge', {
      method: 'POST',
      body: { currentPassword: 'a good password' },
    })
  })

  it('offers nothing to delete when there are no orphans', async () => {
    requestMock.mockImplementation((path: string) =>
      Promise.resolve(path === '/web/admin/storage' ? { ...STORAGE, orphanFiles: 0 } : {}),
    )

    const wrapper = await open('storage')

    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
  })

  it('does not fetch a section that is not showing', async () => {
    await open()

    expect(requestMock).not.toHaveBeenCalledWith('/web/admin/storage')
  })
})

describe('the retention screen', () => {
  it('shows the periods in force', async () => {
    const wrapper = await open('retention')

    const values = wrapper.findAll('input').map((input) => (input.element as HTMLInputElement).value)
    expect(values).toEqual(['0', '0', '24'])
  })

  it('says what a period would take before it takes it', async () => {
    /* A period is a decision about deleting other people's work; a rehearsal
       is what makes setting one safe. */
    const wrapper = await open('retention')

    await button(wrapper, 'See what would go').trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/admin/retention/run?preview=true', {
      method: 'POST',
    })
    expect(wrapper.text()).toContain('Would delete: 3 items out of the trash')
  })

  it('reports a sweep in the reader’s own language, not the server’s sentence', async () => {
    i18n.global.locale.value = 'de'
    const wrapper = await open('retention')

    await button(wrapper, 'Jetzt löschen').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('Gelöscht: 3 Einträge aus dem Papierkorb')
    i18n.global.locale.value = 'en'
  })

  it('refuses to save something the server would refuse', async () => {
    const wrapper = await open('retention')

    await wrapper.findAll('input')[0].setValue('-1')

    expect(button(wrapper, 'Save').attributes('disabled')).toBeDefined()
  })
})

describe('the accounts screen', () => {
  it('lists the accounts and marks what each one is', async () => {
    const wrapper = await open('accounts')

    expect(wrapper.text()).toContain('Ada')
    expect(wrapper.text()).toContain('Administrator')
    expect(wrapper.text()).toContain('Suspended')
  })

  it('asks for the administrator’s own password before anything can be done', async () => {
    const wrapper = await open('accounts')

    await wrapper.findAll('.accounts__row')[1].trigger('click')

    expect(button(wrapper, 'Suspend').attributes('disabled')).toBeDefined()
  })

  it('suspends an account once the password is there', async () => {
    const wrapper = await open('accounts')
    await wrapper.findAll('.accounts__row')[1].trigger('click')

    await wrapper.findAll('input[type="password"]')[0].setValue('a good password')
    await button(wrapper, 'Suspend').trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/admin/users/2', {
      method: 'PATCH',
      body: { disabled: true, currentPassword: 'a good password' },
    })
  })

  it('offers to reinstate one that is already suspended', async () => {
    const wrapper = await open('accounts')

    await wrapper.findAll('.accounts__row')[2].trigger('click')

    expect(button(wrapper, 'Reinstate')).toBeTruthy()
  })

  it('shows a new account’s password once', async () => {
    /* The only time anybody sees it, exactly as an API key is shown once. */
    const wrapper = await open('accounts')

    await button(wrapper, 'Create account').trigger('click')
    await wrapper.findAll('input')[0].setValue('rita')
    await wrapper.findAll('input[type="password"]')[0].setValue('a password for rita')
    await wrapper.findAll('input[type="password"]')[1].setValue('mine')
    // The form rather than the button: jsdom does not submit one from a click.
    await wrapper.get('.accounts__form').trigger('submit')
    await flush()

    expect(wrapper.get('.card__inset').text()).toContain('a password for rita')
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
