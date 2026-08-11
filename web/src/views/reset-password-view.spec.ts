import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { i18n } from '@/i18n'

import ResetPasswordView from './ResetPasswordView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en'
  requestMock.mockReset()
  requestMock.mockResolvedValue({ username: 'grace', displayName: 'Grace' })
})

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve))
  await new Promise((resolve) => setTimeout(resolve))
}

async function open(query = '?token=abc') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/reset', name: 'reset-password', component: ResetPasswordView },
      { path: '/sign-in', name: 'sign-in', component: { template: '<div />' } },
    ],
  })
  await router.push(`/reset${query}`)
  await router.isReady()

  const wrapper = mount(ResetPasswordView, { global: { plugins: [i18n, router] } })
  await flush()
  return wrapper
}

describe('setting a password from a link', () => {
  it('names the account before asking for a password', async () => {
    /* Somebody sent the wrong link should see that before typing anything. */
    const wrapper = await open()

    expect(wrapper.text()).toContain('grace')
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
  })

  it('says so when the link has expired, without taking a password first', async () => {
    requestMock.mockRejectedValue(new ApiError('That link is not valid or has expired', 403))

    const wrapper = await open()

    expect(wrapper.text()).toContain('not valid or has expired')
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
  })

  it('refuses a link with no token at all', async () => {
    const wrapper = await open('')

    expect(requestMock).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('sets the password and offers the way in', async () => {
    const wrapper = await open()

    await wrapper.get('input[type="password"]').setValue('a password of my own')
    await wrapper.get('form').trigger('submit')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/auth/reset', {
      method: 'POST',
      body: { token: 'abc', password: 'a password of my own' },
    })
    expect(wrapper.text()).toContain('Password set')
  })

  it('keeps the form open when the server refuses the password', async () => {
    /* The link is not spent by a refused password, so asking again is right. */
    const wrapper = await open()
    requestMock.mockRejectedValueOnce(new ApiError('A password must be at least 8 characters', 400))

    await wrapper.get('input[type="password"]').setValue('short')
    await wrapper.get('form').trigger('submit')
    await flush()

    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('at least 8 characters')
  })
})
