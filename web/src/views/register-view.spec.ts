import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n, loadLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import RegisterView from './RegisterView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))
vi.mock('@/api/client', async (original) => ({
  ...(await original<typeof import('@/api/client')>()), request: requestMock,
}))
beforeAll(() => loadLocale('en-US'))
beforeEach(() => {
  setActivePinia(createPinia())
  requestMock.mockReset().mockResolvedValue({})
})

async function open() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/register', component: RegisterView },
    { path: '/sign-in', name: 'sign-in', component: { template: '<div />' } },
  ] })
  await router.push('/register')
  await router.isReady()
  return mount(RegisterView, { global: { plugins: [i18n, router] } })
}

it('requests an account without collecting or submitting a password', async () => {
  const auth = useAuthStore()
  auth.registrationApproval = true
  const wrapper = await open()
  expect(wrapper.find('input[type=password]').exists()).toBe(false)
  await wrapper.find('input[autocomplete=username]').setValue('Ada')
  await wrapper.find('input[type=email]').setValue('ada@example.org')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(requestMock).toHaveBeenCalledWith('/web/registration/apply', {
    method: 'POST', body: { username: 'Ada', email: 'ada@example.org', displayName: '' },
  })
  expect(wrapper.text()).toContain('Check your email')
  expect(auth.user).toBeNull()
})

it('keeps the first-owner bootstrap form password-based', async () => {
  const auth = useAuthStore()
  auth.registrationApproval = true
  auth.firstAccount = true
  const wrapper = await open()
  expect(wrapper.findAll('input[type=password]')).toHaveLength(2)
})
