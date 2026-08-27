import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { i18n } from '@/i18n'

import ForgotPasswordView from './ForgotPasswordView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en-US'
  requestMock.mockReset()
  requestMock.mockResolvedValue(undefined)
})

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve))
  await new Promise((resolve) => setTimeout(resolve))
}

async function open() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/forgot', name: 'forgot-password', component: ForgotPasswordView },
      { path: '/sign-in', name: 'sign-in', component: { template: '<div />' } },
    ],
  })
  await router.push('/forgot')
  await router.isReady()

  const wrapper = mount(ForgotPasswordView, { global: { plugins: [i18n, router] } })
  await flush()
  return wrapper
}

async function ask(wrapper: Awaited<ReturnType<typeof open>>, address: string): Promise<void> {
  await wrapper.find('input').setValue(address)
  await wrapper.find('form').trigger('submit')
  await flush()
}

describe('asking for a link to set a new password', () => {
  it('sends the address to the server', async () => {
    const wrapper = await open()

    await ask(wrapper, 'grace@example.org')

    expect(requestMock).toHaveBeenCalledWith('/web/auth/forgot', {
      method: 'POST',
      body: { email: 'grace@example.org' },
    })
  })

  it('answers with a conditional rather than a promise', async () => {
    /* The screen is not told whether anything was found, and must not imply
       it was: "if an account here uses that address" is the whole claim. */
    const wrapper = await open()

    await ask(wrapper, 'grace@example.org')

    expect(wrapper.text()).toContain('If an account here uses that address')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('says the same thing for an address that has no account', async () => {
    /* The server answers 202 either way; this checks the screen does not find
       some other way to tell the two apart. */
    const known = await open()
    await ask(known, 'grace@example.org')
    const unknown = await open()

    await ask(unknown, 'nobody@example.org')

    expect(unknown.text()).toBe(known.text())
  })

  it('offers the way back to signing in', async () => {
    const wrapper = await open()

    await ask(wrapper, 'grace@example.org')

    expect(wrapper.text()).toContain('Back to sign in')
  })

  it('keeps the form open when the server could not be reached', async () => {
    /* Distinct from a refusal, which this endpoint never gives: the address
       has not been submitted, so retyping it would be the only way back. */
    requestMock.mockRejectedValue(new ApiError('Could not reach the server', 0))
    const wrapper = await open()

    await ask(wrapper, 'grace@example.org')

    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.text()).toContain('Could not reach the server')
  })

  it('does not submit an empty address', async () => {
    const wrapper = await open()

    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
  })
})
