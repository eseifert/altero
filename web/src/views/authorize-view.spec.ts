import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

import AuthorizeView from './AuthorizeView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const PENDING = {
  handle: 'opaque',
  clientId: 'notebook',
  name: 'Notebook',
  description: 'Reads your library into a notebook',
  scopes: ['openid', 'library.read'],
  newScopes: ['openid', 'library.read'],
  alreadyGranted: false,
}

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en'
  requestMock.mockReset()
  requestMock.mockResolvedValue(PENDING)
})

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve))
  await new Promise((resolve) => setTimeout(resolve))
}

async function open(query = '?request=opaque') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/authorize', name: 'authorize', component: AuthorizeView },
      { path: '/library', name: 'library', component: { template: '<div />' } },
    ],
  })
  await router.push(`/authorize${query}`)
  await router.isReady()

  const wrapper = mount(AuthorizeView, { global: { plugins: [i18n, router] } })
  await flush()
  return wrapper
}

describe('the consent screen', () => {
  it('describes the application the server named', async () => {
    const auth = useAuthStore()
    auth.user = { id: 1, username: 'ada' } as never

    const wrapper = await open()

    expect(requestMock).toHaveBeenCalledWith('/web/oauth/pending/opaque')
    expect(wrapper.text()).toContain('Notebook')
    expect(wrapper.text()).toContain('Reads your library into a notebook')
  })

  it('says what each scope means rather than showing its name', async () => {
    const wrapper = await open()

    expect(wrapper.text()).toContain('Read everything in your library')
    expect(wrapper.text()).not.toContain('library.read')
  })

  it('shows a scope it does not recognise rather than hiding it', async () => {
    /* A grant the interface cannot describe is still a grant. Hiding it would
       be the consent screen lying by omission. */
    requestMock.mockResolvedValue({ ...PENDING, scopes: ['openid', 'invented.scope'] })

    const wrapper = await open()

    expect(wrapper.text()).toContain('invented.scope')
  })

  it('takes nothing from the query string but the handle', async () => {
    /* The whole reason the handle is opaque: a screen whose text came from the
       link that opened it describes whatever the link says. */
    const wrapper = await open('?request=opaque&name=Trustworthy%20Bank&scope=openid')

    expect(wrapper.text()).toContain('Notebook')
    expect(wrapper.text()).not.toContain('Trustworthy Bank')
  })

  it('has no password field, because signing in happens elsewhere', async () => {
    const wrapper = await open()

    expect(wrapper.findAll('input[type="password"]')).toHaveLength(0)
  })

  it('says plainly when nothing on offer reaches a library', async () => {
    requestMock.mockResolvedValue({ ...PENDING, scopes: ['openid', 'profile'] })

    const wrapper = await open()

    expect(wrapper.text()).toContain('It cannot read your library')
  })

  it('does not claim that when the library is on offer', async () => {
    const wrapper = await open()

    expect(wrapper.text()).not.toContain('It cannot read your library')
  })

  it('marks what is new where consent was given before', async () => {
    requestMock.mockResolvedValue({
      ...PENDING,
      scopes: ['openid', 'library.read', 'library.write'],
      newScopes: ['library.write'],
    })

    const wrapper = await open()

    expect(wrapper.findAll('.authorize__badge')).toHaveLength(1)
    expect(wrapper.text()).toContain('Add, change and remove things in your library')
  })

  it('answers and leaves for the address the server returned', async () => {
    const assign = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { assign },
      writable: true,
    })
    const wrapper = await open()
    requestMock.mockResolvedValue({ redirect: 'https://app.example.com/callback?code=abc' })

    await wrapper.findAll('button')[0].trigger('click')
    await flush()

    expect(requestMock).toHaveBeenLastCalledWith('/web/oauth/pending/opaque', {
      method: 'POST',
      body: { approve: true },
    })
    expect(assign).toHaveBeenCalledWith('https://app.example.com/callback?code=abc')
  })

  it('tells the application when it is refused rather than going nowhere', async () => {
    const assign = vi.fn()
    Object.defineProperty(window, 'location', { value: { assign }, writable: true })
    const wrapper = await open()
    requestMock.mockResolvedValue({
      redirect: 'https://app.example.com/callback?error=access_denied',
    })

    await wrapper.findAll('button')[1].trigger('click')
    await flush()

    expect(requestMock).toHaveBeenLastCalledWith('/web/oauth/pending/opaque', {
      method: 'POST',
      body: { approve: false },
    })
    expect(assign).toHaveBeenCalledWith('https://app.example.com/callback?error=access_denied')
  })

  it('says so when the link carries no request at all', async () => {
    const wrapper = await open('')

    expect(wrapper.text()).toContain('That link is missing its request.')
    expect(requestMock).not.toHaveBeenCalled()
  })
})
