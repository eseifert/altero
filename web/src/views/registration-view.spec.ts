import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n, loadLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import RegistrationView from './RegistrationView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))
vi.mock('@/api/client', async (original) => ({
  ...(await original<typeof import('@/api/client')>()), request: requestMock,
}))
beforeAll(() => loadLocale('en-US'))
beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.spyOn(useAuthStore(), 'loadConfig').mockResolvedValue()
  requestMock.mockReset().mockResolvedValue({ requestID: 1, status: 'review_pending', expires: '2026-12-01T00:00:00Z' })
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

async function open(hash = '') {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/registration', component: RegistrationView },
    { path: '/register', name: 'register', component: { template: '<div />' } },
    { path: '/sign-in', name: 'sign-in', component: { template: '<div />' } },
  ] })
  await router.push('/registration' + hash)
  await router.isReady()
  const wrapper = mount(RegistrationView, { global: { plugins: [i18n, router] } })
  await flushPromises()
  return { wrapper, router }
}

it('removes the mailbox proof from the URL and requires an explicit confirmation', async () => {
  const { wrapper, router } = await open('#token=mailbox-proof')
  expect(router.currentRoute.value.hash).toBe('')
  expect(requestMock).not.toHaveBeenCalled()
  await wrapper.find('button').trigger('click')
  await flushPromises()
  expect(requestMock).toHaveBeenCalledWith('/web/registration/verify', {
    method: 'POST', body: { token: 'mailbox-proof' },
  })
  expect(requestMock).toHaveBeenCalledWith('/web/registration')
  expect(useAuthStore().isAuthenticated).toBe(false)
  wrapper.unmount()
})

it('polls pending status and stops after leaving the page', async () => {
  const { wrapper } = await open()
  expect(requestMock).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(15000)
  expect(requestMock).toHaveBeenCalledTimes(2)
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(30000)
  expect(requestMock).toHaveBeenCalledTimes(2)
})

it('enrolls an approved applicant without creating an ordinary session', async () => {
  requestMock.mockResolvedValue({ requestID: 1, status: 'approved', expires: '2026-12-01T00:00:00Z' })
  const { wrapper } = await open()
  const inputs = wrapper.findAll('input[type=password]')
  expect(inputs).toHaveLength(2)
  await inputs[0]!.setValue('a long personal passphrase')
  await inputs[1]!.setValue('a long personal passphrase')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(requestMock).toHaveBeenCalledWith('/web/registration/enroll', {
    method: 'POST', body: { password: 'a long personal passphrase' },
  })
  expect(wrapper.find('input[type=password]').exists()).toBe(false)
  expect(useAuthStore().isAuthenticated).toBe(false)
  wrapper.unmount()
})

it('does not start polling after unmount during initial configuration', async () => {
  let resolve!: () => void
  vi.mocked(useAuthStore().loadConfig).mockImplementation(() => new Promise<void>((done) => { resolve = done }))
  const { wrapper } = await open()
  wrapper.unmount()
  resolve()
  await flushPromises()
  expect(vi.getTimerCount()).toBe(0)
  expect(requestMock).not.toHaveBeenCalled()
})
