import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { i18n } from '@/i18n'

import LinkClientView from './LinkClientView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

interface Proof {
  password: boolean
  fresh: boolean
  providers: { slug: string; displayName: string }[]
}

const WITH_A_PASSWORD: Proof = { password: true, fresh: false, providers: [] }
const THROUGH_A_DIRECTORY: Proof = {
  password: false,
  fresh: false,
  providers: [{ slug: 'campus', displayName: 'Campus' }],
}

/** Answer the page's requests: the link request, then whatever proof is current. */
function serve(...proofs: Proof[]): void {
  requestMock.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (path === '/web/account/proof') return proofs.length > 1 ? proofs.shift() : proofs[0]
    if (path === '/web/link/abc' && !options?.method) {
      return {
        status: 'pending',
        requestedUserId: null,
        expiresInSeconds: 1800,
        canApprove: true,
        reason: null,
      }
    }
    return undefined
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en-US'
  requestMock.mockReset()
})

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve))
  await new Promise((resolve) => setTimeout(resolve))
}

async function open(): Promise<ReturnType<typeof mount>> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/link', name: 'link-client', component: LinkClientView },
      { path: '/library', name: 'library', component: { template: '<div />' } },
    ],
  })
  await router.push('/link?token=abc')
  await router.isReady()

  const wrapper = mount(LinkClientView, { global: { plugins: [i18n, router] } })
  await flush()
  return wrapper
}

const connect = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('button').find((button) => button.text() === 'Connect')!

describe('connecting Zotero', () => {
  it('asks an account with a password for it', async () => {
    serve(WITH_A_PASSWORD)
    const wrapper = await open()

    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(connect(wrapper).attributes('disabled')).toBeDefined()

    await wrapper.find('input[type="password"]').setValue('correct horse')
    await connect(wrapper).trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/link/abc/approve', {
      method: 'POST',
      body: { currentPassword: 'correct horse' },
    })
    expect(wrapper.text()).toContain('Done.')
  })

  it('sends an account with no password back through its directory', async () => {
    serve(THROUGH_A_DIRECTORY)
    const wrapper = await open()

    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(connect(wrapper).attributes('disabled')).toBeDefined()

    const link = wrapper.find('a.auth-form__provider')
    expect(link.text()).toBe('Confirm with Campus')
    // Back to this very request, which is what makes the trip worth taking.
    expect(link.attributes('href')).toBe(
      '/web/auth/sso/campus/start?purpose=reauth&next=%2Flink%3Ftoken%3Dabc',
    )
  })

  it('asks nothing of a browser that has just proved itself', async () => {
    serve({ ...THROUGH_A_DIRECTORY, fresh: true })
    const wrapper = await open()

    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(wrapper.find('a.auth-form__provider').exists()).toBe(false)
    expect(wrapper.text()).toContain('You have just confirmed it is you.')

    await connect(wrapper).trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/link/abc/approve', {
      method: 'POST',
      body: { currentPassword: '' },
    })
  })

  it('offers the directory again when the proof lapsed while the page stood open', async () => {
    serve({ ...THROUGH_A_DIRECTORY, fresh: true }, THROUGH_A_DIRECTORY)
    const wrapper = await open()
    const approve = requestMock.getMockImplementation()!
    requestMock.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path === '/web/link/abc/approve') {
        throw new ApiError('This needs you to confirm it is you before it can go ahead', 403)
      }
      return approve(path, options)
    })

    await connect(wrapper).trigger('click')
    await flush()

    expect(wrapper.text()).toContain('This needs you to confirm it is you before it can go ahead')
    expect(wrapper.find('a.auth-form__provider').exists()).toBe(true)
    expect(connect(wrapper).attributes('disabled')).toBeDefined()
  })

  it('says so when the account has nothing to prove itself with', async () => {
    serve({ password: false, fresh: false, providers: [] })
    const wrapper = await open()

    expect(wrapper.text()).toContain('An administrator can set a password for it.')
    expect(connect(wrapper).attributes('disabled')).toBeDefined()
  })
})
