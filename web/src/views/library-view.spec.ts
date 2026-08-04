import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useLibraryStore } from '@/stores/library'

import LibraryView from './LibraryView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const LIBRARIES = [{ id: 1, type: 'user', ownerId: 1, name: 'Ada', version: 4, prefix: '/users/1' }]

const ITEM = {
  key: 'AAAA2345',
  version: 1,
  data: { itemType: 'book', title: 'Structure and Interpretation' },
  meta: {},
}

beforeEach(() => {
  setActivePinia(createPinia())
  requestMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/libraries') return Promise.resolve(LIBRARIES)
    if (path.startsWith('/web/schema')) {
      return Promise.resolve({ itemTypes: {}, fields: {}, creatorTypes: {} })
    }
    if (path.includes('/collections')) return Promise.resolve({ collections: [] })
    if (path.includes('/tags')) return Promise.resolve({ tags: [] })
    if (path.includes('/children')) return Promise.resolve({ items: [] })
    return Promise.resolve({ total: 1, items: [ITEM] })
  })
})

async function open() {
  const wrapper = mount(LibraryView)
  await new Promise((resolve) => setTimeout(resolve, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('the detail pane', () => {
  it('is absent until an item is selected', async () => {
    /* An empty third column would take a fifth of the width to say nothing,
       and the width is what the item list needs. */
    const wrapper = await open()

    expect(wrapper.find('.library__detail').exists()).toBe(false)
    expect(wrapper.get('.library').classes()).not.toContain('library--detail')
  })

  it('appears once something is selected', async () => {
    const wrapper = await open()

    await wrapper.get('.library__row:not(.library__row--head)').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.library__detail').exists()).toBe(true)
    expect(wrapper.get('.library').classes()).toContain('library--detail')
  })

  it('can be closed again, which is the only way back to the wider list', async () => {
    const wrapper = await open()
    await wrapper.get('.library__row:not(.library__row--head)').trigger('click')
    await wrapper.vm.$nextTick()

    await wrapper.get('.detail__close').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.library__detail').exists()).toBe(false)
    expect(useLibraryStore().selected).toBeNull()
  })
})

describe('the item list', () => {
  it('shows the title of each item', async () => {
    const wrapper = await open()

    expect(wrapper.get('.library__cell--title').text()).toBe('Structure and Interpretation')
  })
})
