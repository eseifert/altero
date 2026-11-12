import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { i18n, loadLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import AdminView from './AdminView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))
vi.mock('@/api/client', async (original) => ({
  ...(await original<typeof import('@/api/client')>()), request: requestMock,
}))
beforeAll(() => loadLocale('en-US'))
beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().registrationApproval = true
  vi.spyOn(useAuthStore(), 'loadConfig').mockResolvedValue()
  requestMock.mockReset().mockImplementation((path: string) => Promise.resolve(
    path === '/web/admin/registrations?after_id=0&limit=50'
      ? { requests: [{ id: 7, username: 'Ada', email: 'ada@example.org', displayName: 'Ada', created: '2026-11-12T12:00:00Z', expires: '2026-11-19T12:00:00Z' }] }
      : path === '/web/account/proof' ? { fresh: false, password: true, providers: [] } : {},
  ))
})
async function open() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/admin/:section?', name: 'admin', component: AdminView },
  ] })
  await router.push('/admin/registrations'); await router.isReady()
  const wrapper = mount(AdminView, { global: { plugins: [i18n, router] } })
  await flushPromises()
  return wrapper
}
it('reviews a verified applicant with explicit identity confirmation before approval', async () => {
  const wrapper = await open()
  expect(wrapper.text()).toContain('ada@example.org')
  const choose = wrapper.findAll('button').find((button) => button.text() === 'Review')!
  await choose.trigger('click'); await flushPromises()
  const approve = wrapper.findAll('button').find((button) => button.text() === 'Approve')!
  expect(approve.attributes('disabled')).toBeDefined()
  await wrapper.find('input[autocomplete=current-password]').setValue('operator proof')
  await flushPromises()
  expect(approve.attributes('disabled')).toBeUndefined()
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(requestMock).toHaveBeenCalledWith('/web/admin/registrations/7/approve', {
    method: 'POST', body: { currentPassword: 'operator proof' },
  })
  wrapper.unmount()
})
it('rejects without requesting a password and refreshes the queue', async () => {
  const wrapper = await open()
  await wrapper.findAll('button').find((button) => button.text() === 'Review')!.trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find((button) => button.text() === 'Reject')!.trigger('click')
  await flushPromises()
  expect(requestMock).toHaveBeenCalledWith('/web/admin/registrations/7/reject', { method: 'POST', body: {} })
  expect(requestMock.mock.calls.filter(([path]) => path === '/web/admin/registrations?after_id=0&limit=50')).toHaveLength(2)
  wrapper.unmount()
})
