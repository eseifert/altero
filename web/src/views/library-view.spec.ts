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

describe('the search field', () => {
  it('offers nothing to clear while it is empty', async () => {
    const wrapper = await open()

    expect(wrapper.find('.library__search-clear').exists()).toBe(false)
  })

  it('offers a clear once something has been typed', async () => {
    const wrapper = await open()

    await wrapper.get('.library__search-field').setValue('whales')

    expect(wrapper.find('.library__search-clear').exists()).toBe(true)
  })

  it('empties the field and the query when it is used', async () => {
    const wrapper = await open()
    await wrapper.get('.library__search-field').setValue('whales')

    await wrapper.get('.library__search-clear').trigger('click')

    expect((wrapper.get('.library__search-field').element as HTMLInputElement).value).toBe('')
    expect(useLibraryStore().search).toBe('')
  })

  it('clears at once rather than waiting out the typing pause', async () => {
    /* The pause exists so that typing is one query per phrase. Pressing a
       button is not typing, and a list that keeps its old results for another
       quarter of a second reads as a click that did not register. */
    const wrapper = await open()
    const store = useLibraryStore()

    vi.useFakeTimers()
    try {
      // Typed under fake timers, so the pause it starts is ours to advance.
      await wrapper.get('.library__search-field').setValue('whales')
      await vi.advanceTimersByTimeAsync(300)
      expect(store.search).toBe('whales')

      await wrapper.get('.library__search-clear').trigger('click')

      // Asserted without letting any timer run: the query is already gone.
      expect(store.search).toBe('')
    } finally {
      vi.useRealTimers()
    }
  })
})
