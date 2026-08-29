import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { i18n } from '@/i18n'

import DeviceView from './DeviceView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en-US'
  requestMock.mockReset()
  requestMock.mockResolvedValue({ handle: 'opaque' })
})

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve))
  await new Promise((resolve) => setTimeout(resolve))
}

async function open(path = '/device'): Promise<{
  wrapper: ReturnType<typeof mount>
  router: Router
}> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/device', name: 'device', component: DeviceView },
      { path: '/device/done', name: 'device-done', component: DeviceView },
      { path: '/authorize', name: 'authorize', component: { template: '<div />' } },
      { path: '/library', name: 'library', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()

  const wrapper = mount(DeviceView, { global: { plugins: [i18n, router] } })
  await flush()
  return { wrapper, router }
}

describe('the device page', () => {
  it('asks for the code the device is showing', async () => {
    const { wrapper } = await open()

    expect(wrapper.text()).toContain('Enter the code shown on your device')
    expect(wrapper.find('input').exists()).toBe(true)
  })

  it('sends the code and goes on to the consent screen', async () => {
    const { wrapper, router } = await open()
    await wrapper.find('input').setValue('WDJB-MJHT')

    await wrapper.find('button').trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/oauth/device', {
      method: 'POST',
      body: { userCode: 'WDJB-MJHT' },
    })
    expect(router.currentRoute.value.fullPath).toBe('/authorize?request=opaque')
  })

  it('fills the code in from the link the device showed', async () => {
    const { wrapper } = await open('/device?code=WDJB-MJHT')

    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('WDJB-MJHT')
  })

  it('says what went wrong rather than moving on', async () => {
    requestMock.mockRejectedValue(new Error('No device is waiting for that code'))
    const { wrapper, router } = await open()
    await wrapper.find('input').setValue('ZZZZ-ZZZZ')

    await wrapper.find('button').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('No device is waiting for that code')
    expect(router.currentRoute.value.fullPath).toBe('/device')
  })

  it('sends nothing when nothing was typed', async () => {
    const { wrapper } = await open()

    await wrapper.find('button').trigger('click')
    await flush()

    expect(requestMock).not.toHaveBeenCalled()
  })

  it('tells somebody to go back to their device once they have answered', async () => {
    const { wrapper } = await open('/device/done')

    expect(wrapper.text()).toContain('You can go back to your device now')
    expect(wrapper.find('input').exists()).toBe(false)
  })
})
