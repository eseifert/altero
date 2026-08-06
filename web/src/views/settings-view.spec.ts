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

const MINE = { id: 1, type: 'user', ownerId: 1, name: 'Ada', version: 4, prefix: '/users/1' }
/** A group this account is in. What it may do there is set per test. */
const GROUP = { id: 2, type: 'group', ownerId: 7, name: 'Engine', version: 9, prefix: '/groups/7' }

let groups: { id: number; role: string; owner: boolean }[] = []
let libraries: unknown[] = [MINE]

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en'
  groups = []
  libraries = [MINE]
  requestMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/account') return Promise.resolve(ACCOUNT)
    if (path === '/web/account/keys') return Promise.resolve({ keys: [] })
    if (path === '/web/account/locales') return Promise.resolve({ languages: [], timeZones: [] })
    if (path === '/web/libraries') return Promise.resolve(libraries)
    if (path === '/web/groups') return Promise.resolve({ groups })
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

    expect(wrapper.findAll('.settings__section')).toHaveLength(6)
    expect(wrapper.text()).toContain('Import and export')
    expect(wrapper.text()).toContain('Move from zotero.org')
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

describe('import and export', () => {
  it('offers the personal library for export', async () => {
    const { wrapper } = await open('import-export')

    const download = wrapper.get('.settings__download')
    expect(download.attributes('href')).toBe('/web/libraries/1/archive')
    expect(download.attributes('download')).toBeDefined()
  })

  it('offers a group to an administrator', async () => {
    libraries = [MINE, GROUP]
    groups = [{ id: 2, role: 'admin', owner: false }]

    const { wrapper } = await open('import-export')

    const links = wrapper.findAll('.settings__download').map((a) => a.attributes('href'))
    expect(links).toEqual(['/web/libraries/1/archive', '/web/libraries/2/archive'])
  })

  it('offers a group to a plain member for neither', async () => {
    /* The server refuses either way, and a control that will be refused is a
       promise the screen cannot keep. */
    libraries = [MINE, GROUP]
    groups = [{ id: 2, role: 'member', owner: false }]

    const { wrapper } = await open('import-export')

    const links = wrapper.findAll('.settings__download').map((a) => a.attributes('href'))
    expect(links).toEqual(['/web/libraries/1/archive'])
    const targets = wrapper.get('select').findAll('option').map((option) => option.text())
    expect(targets).toEqual(['Ada'])
  })

  it('lets only the owner of a group restore over it', async () => {
    libraries = [MINE, GROUP]
    groups = [{ id: 2, role: 'admin', owner: true }]

    const { wrapper } = await open('import-export')

    const targets = wrapper.get('select').findAll('option').map((option) => option.text())
    expect(targets).toEqual(['Ada', 'Engine'])
  })

  it('will not restore until an archive has been chosen', async () => {
    const { wrapper } = await open('import-export')

    const restore = wrapper.findAll('button').find((button) => button.text() === 'Restore')
    expect(restore?.attributes('disabled')).toBeDefined()
  })

  it('sends the archive, the password and the replace flag together', async () => {
    const { wrapper } = await open('import-export')
    const file = new File(['PK'], 'library.zip', { type: 'application/zip' })
    // jsdom will not let a file input be filled from script, so the handler is
    // driven the way the browser drives it.
    wrapper.get('input[type="file"]').element.dispatchEvent(new Event('change'))
    const section = wrapper.getComponent({ name: 'TransferSection' })
    ;(section.vm as unknown as { file: File | null }).file = file
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await settle(wrapper)

    const restore = wrapper.findAll('button').find((button) => button.text() === 'Restore')
    await restore?.trigger('click')
    await settle(wrapper)

    const [path, options] = requestMock.mock.calls.find(
      ([, options]) => options?.method === 'POST',
    ) as [string, { body: FormData }]
    expect(path).toBe('/web/libraries/1/archive')
    expect(options.body.get('archive')).toBe(file)
    expect(options.body.get('currentPassword')).toBe('correct horse')
    expect(options.body.get('replace')).toBe('true')
  })

  it('says what replacing costs, before it is done rather than after', async () => {
    const { wrapper } = await open('import-export')

    expect(wrapper.find('.settings__warning').exists()).toBe(false)

    await wrapper.get('input[type="checkbox"]').setValue(true)

    expect(wrapper.get('.settings__warning').text()).toContain('Everything in Ada is deleted first')
  })
})

describe('moving a library in from zotero.org', () => {
  /** Answer the status endpoint with `states`, one per poll. */
  function polling(states: unknown[], onStart?: (body: unknown) => unknown) {
    const remaining = [...states]
    requestMock.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === '/web/migrate/zotero' && options?.method === 'POST') {
        return Promise.resolve(onStart ? onStart(options.body) : remaining[0])
      }
      if (path === '/web/migrate/zotero') {
        return Promise.resolve(remaining.length > 1 ? remaining.shift() : remaining[0])
      }
      if (path === '/web/account') return Promise.resolve(ACCOUNT)
      if (path === '/web/libraries') return Promise.resolve(libraries)
      if (path === '/web/groups') return Promise.resolve({ groups })
      return Promise.resolve({})
    })
  }

  const IDLE = null
  const FINISHED = {
    running: false,
    stage: 'done',
    done: 3,
    total: 3,
    detail: '',
    error: null,
    summary: {
      userID: 4711,
      username: 'ada',
      libraryVersion: 12,
      items: 3,
      collections: 1,
      searches: 0,
      tags: 2,
      files: 1,
      filesMissing: [],
      skipped: [],
      rewritten: 0,
      complete: true,
    },
  }

  it('says a key is needed rather than a zotero.org password', async () => {
    polling([IDLE])
    const { wrapper } = await open('migrate')

    expect(wrapper.text()).toContain('no password sign-in for other programs')
    expect(wrapper.text()).toContain('create a new private key')
  })

  it('will not start without a key', async () => {
    polling([IDLE])
    const { wrapper } = await open('migrate')

    const button = wrapper.findAll('button').find((entry) => entry.text().includes('Copy my library'))
    expect(button?.attributes('disabled')).toBeDefined()
  })

  it('sends the key, the password and the choice to replace', async () => {
    let sent: unknown = null
    polling([FINISHED], (body) => {
      sent = body
      return FINISHED
    })
    const { wrapper } = await open('migrate')

    const fields = wrapper.findAll('input')
    await fields[0].setValue('KEYFROMZOTERO')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('input[type="password"]').setValue('correct horse')
    await wrapper
      .findAll('button')
      .find((entry) => entry.text().includes('Copy my library'))!
      .trigger('click')
    await settle(wrapper)

    expect(sent).toEqual({
      apiKey: 'KEYFROMZOTERO',
      currentPassword: 'correct horse',
      replace: true,
    })
  })

  it('says what replacing costs, before it is done rather than after', async () => {
    polling([IDLE])
    const { wrapper } = await open('migrate')

    expect(wrapper.find('.settings__warning').exists()).toBe(false)

    await wrapper.get('input[type="checkbox"]').setValue(true)

    expect(wrapper.get('.settings__warning').text()).toContain('deleted first')
  })

  it('shows what a finished migration brought across', async () => {
    polling([FINISHED])
    const { wrapper } = await open('migrate')

    expect(wrapper.text()).toContain('Finished.')
    expect(wrapper.text()).toContain('3 items, 1 collections, 2 tags and 1 files')
    expect(wrapper.text()).toContain('ada')
  })

  it('reports one that stopped, rather than looking finished', async () => {
    polling([
      {
        running: false,
        stage: 'failed',
        done: 0,
        total: null,
        detail: '',
        error: 'zotero.org refused that key.',
      },
    ])
    const { wrapper } = await open('migrate')

    expect(wrapper.get('.settings__warning[role="alert"]').text()).toContain('refused that key')
  })

  it('names what did not come across, rather than reporting a clean run', async () => {
    polling([
      {
        ...FINISHED,
        summary: {
          ...FINISHED.summary,
          filesMissing: ['AAAA2345', 'BBBB2345'],
          skipped: [{ key: 'CCCC2345', reason: 'Invalid field' }],
          complete: false,
        },
      },
    ])
    const { wrapper } = await open('migrate')

    expect(wrapper.text()).toContain('2 attachments had no file stored at zotero.org')
    expect(wrapper.text()).toContain('CCCC2345')
  })

  it('hides the form while one is running, so a second cannot be started', async () => {
    polling([{ running: true, stage: 'items', done: 120, total: null, detail: '', error: null }])
    const { wrapper } = await open('migrate')

    expect(wrapper.text()).toContain('Reading items…')
    expect(wrapper.text()).toContain('120')
    expect(wrapper.findAll('button').some((entry) => entry.text().includes('Copy my library'))).toBe(
      false,
    )
  })
})
