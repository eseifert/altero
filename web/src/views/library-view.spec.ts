import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { resetLabels } from '@/items/labels'
import { useLibraryStore } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

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

const GERMAN_NAMES = {
  itemTypes: {},
  fields: { title: 'Titel', date: 'Datum' },
  creatorTypes: { creator: 'Ersteller' },
}

beforeEach(() => {
  setActivePinia(createPinia())
  // The display names and the language in force outlive a component, so a test
  // that changes either would otherwise decide what the next one starts from.
  resetLabels()
  i18n.global.locale.value = 'en'
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

/** Let the requests in flight answer, and the answers reach the screen. */
async function settle(wrapper: ReturnType<typeof mount>) {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await wrapper.vm.$nextTick()
}

async function open() {
  const wrapper = mount(LibraryView)
  await settle(wrapper)
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

describe('the column headings', () => {
  function headings(wrapper: ReturnType<typeof mount>): string[] {
    return wrapper.findAll('.library__cell--head').map((cell) => cell.text())
  }

  /** Answer the schema request with the German names, everything else as usual. */
  function speakGerman(): void {
    const usual = requestMock.getMockImplementation()!
    requestMock.mockImplementation((path: string) =>
      path.startsWith('/web/schema') ? Promise.resolve(GERMAN_NAMES) : usual(path),
    )
  }

  it('are the schema’s own names, so a column reads as the field it holds', async () => {
    /* `creator` is the one that is not a field: the schema names it as a
       creator type, which is what the column shows. */
    useLocaleStore().adopt({ language: 'de', timeZone: null })
    speakGerman()

    const wrapper = await open()

    expect(requestMock).toHaveBeenCalledWith('/web/schema?locale=de')
    expect(headings(wrapper).map((text) => text.split(' ')[0])).toEqual([
      'Titel',
      'Ersteller',
      'Datum',
    ])
  })

  it('follow a change of language without the page being reloaded', async () => {
    const wrapper = await open()
    expect(headings(wrapper)[0]).toContain('Title')

    speakGerman()
    useLocaleStore().adopt({ language: 'de', timeZone: null })
    await settle(wrapper)

    expect(headings(wrapper)[0]).toContain('Titel')
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
