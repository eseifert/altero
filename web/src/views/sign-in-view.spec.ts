import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

import SignInView from './SignInView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en'
  requestMock.mockReset()
  requestMock.mockResolvedValue({})
})

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve))
  await new Promise((resolve) => setTimeout(resolve))
}

async function open(query = '') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/sign-in', name: 'sign-in', component: SignInView },
      { path: '/register', name: 'register', component: { template: '<div />' } },
      { path: '/forgot', name: 'forgot-password', component: { template: '<div />' } },
      { path: '/library', name: 'library', component: { template: '<div />' } },
      { path: '/second-factor', name: 'second-factor', component: { template: '<div />' } },
    ],
  })
  await router.push(`/sign-in${query}`)
  await router.isReady()

  const wrapper = mount(SignInView, { global: { plugins: [i18n, router] } })
  await flush()
  return wrapper
}

describe('signing in against a directory', () => {
  it('offers a button per provider the server named', async () => {
    const auth = useAuthStore()
    auth.providers = [
      { slug: 'campus', kind: 'oidc', displayName: 'Campus' },
      { slug: 'library-federation', kind: 'saml', displayName: 'Library Federation' },
    ]

    const wrapper = await open()

    expect(wrapper.text()).toContain('Continue with Campus')
    expect(wrapper.text()).toContain('Continue with Library Federation')
  })

  it('sends the browser to the server rather than fetching', async () => {
    /* The server answers with a redirect to the directory, and only the
       browser's own navigation can carry that. */
    const auth = useAuthStore()
    auth.providers = [{ slug: 'campus', kind: 'oidc', displayName: 'Campus' }]

    const wrapper = await open()

    const link = wrapper.find('a.auth-form__provider')
    expect(link.attributes('href')).toBe(
      '/web/auth/sso/campus/start?next=%2Flibrary',
    )
  })

  it('carries where the reader was going', async () => {
    const auth = useAuthStore()
    auth.providers = [{ slug: 'campus', kind: 'oidc', displayName: 'Campus' }]

    const wrapper = await open('?next=/settings/keys')

    expect(wrapper.find('a.auth-form__provider').attributes('href')).toContain(
      'next=%2Fsettings%2Fkeys',
    )
  })

  it('shows nothing about providers when the instance has none', async () => {
    const wrapper = await open()

    expect(wrapper.find('a.auth-form__provider').exists()).toBe(false)
    // The "or" divider goes with them: it separates nothing on its own.
    expect(wrapper.find('.auth-form__divider').exists()).toBe(false)
  })

  it('still offers the password form when a provider exists', async () => {
    /* Federation is an addition, not a replacement: an instance keeps its
       local accounts. */
    const auth = useAuthStore()
    auth.providers = [{ slug: 'campus', kind: 'oidc', displayName: 'Campus' }]

    const wrapper = await open()

    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
  })
})

describe('why a federated sign-in came back empty-handed', () => {
  it('says so in this reader’s language rather than the directory’s', async () => {
    const wrapper = await open('?error=not-permitted')

    expect(wrapper.text()).toContain('not permitted to use this server')
  })

  it('explains an expired attempt', async () => {
    const wrapper = await open('?error=expired')

    expect(wrapper.text()).toContain('took too long')
  })

  it('falls back to a general sentence for a reason it does not know', async () => {
    /* A newer server redirecting with a slug this build has never heard of
       must still say something. */
    const wrapper = await open('?error=something-invented-later')

    expect(wrapper.text()).toContain('was not completed')
  })

  it('says nothing when there was no error', async () => {
    const wrapper = await open()

    expect(wrapper.find('.auth-form__error').exists()).toBe(false)
  })
})
