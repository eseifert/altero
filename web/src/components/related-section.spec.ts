import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { relatedKeys, useLibraryStore } from '@/stores/library'
import type { ItemEnvelope } from '@/stores/library'

import RelatedSection from './RelatedSection.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

function uri(key: string): string {
  return `http://zotero.org/users/1/items/${key}`
}

function book(key: string, title: string, related: string[] = []): ItemEnvelope {
  return {
    key,
    version: 2,
    data: {
      itemType: 'book',
      title,
      relations: related.length ? { 'dc:relation': related.map(uri) } : {},
    },
    meta: {},
  }
}

const WHALES = book('AAAA2345', 'Whales', ['CCCC2345', 'BBBB2345'])
const SQUID = book('BBBB2345', 'Squid', ['AAAA2345'])
const KRILL = book('CCCC2345', 'Krill', ['AAAA2345'])

/** Answers the listing with whichever of ``items`` it names by key. */
function answerListings(items: ItemEnvelope[]) {
  requestMock.mockImplementation(async (url: string) => {
    const params = new URL(url, 'http://x').searchParams
    const keys = params.get('itemKey')?.split(',') ?? []
    return { items: items.filter((entry) => keys.includes(entry.key)) }
  })
}

function section(item: ItemEnvelope, editable = true) {
  return mount(RelatedSection, { props: { item, editable }, attachTo: document.body })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLibraryStore().libraryId = 1
  requestMock.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('relatedKeys', () => {
  it('takes the key out of each item URI, as the desktop does', () => {
    const item = book('AAAA2345', 'Whales')
    item.data.relations = {
      'dc:relation': [uri('BBBB2345'), 'http://zotero.org/groups/9/items/CCCC2345', uri('BBBB2345')],
      'owl:sameAs': uri('DDDD2345'),
    }

    expect(relatedKeys(item)).toEqual(['BBBB2345', 'CCCC2345'])
  })

  it('reads a single relation, which the API writes as a string', () => {
    const item = book('AAAA2345', 'Whales')
    item.data.relations = { 'dc:relation': uri('BBBB2345') }

    expect(relatedKeys(item)).toEqual(['BBBB2345'])
  })
})

describe('RelatedSection', () => {
  it('lists the related items by title, read from the library by key', async () => {
    answerListings([SQUID, KRILL])
    const wrapper = section(WHALES)
    await flushPromises()

    expect(requestMock).toHaveBeenCalledWith(
      '/web/libraries/1/items?scope=all&itemKey=CCCC2345%2CBBBB2345&limit=100',
    )
    expect(wrapper.findAll('.related__label').map((row) => row.text())).toEqual(['Krill', 'Squid'])
  })

  it('opens a related item when it is pressed', async () => {
    answerListings([SQUID, KRILL])
    const wrapper = section(WHALES)
    await flushPromises()

    await wrapper.findAll('.related__item')[1].trigger('click')

    expect(wrapper.emitted('open')).toEqual([[SQUID]])
  })

  it('reads the trash too for an item that is in it', async () => {
    answerListings([SQUID])
    section({ ...WHALES, data: { ...WHALES.data, deleted: true } })
    await flushPromises()

    const scopes = requestMock.mock.calls.map(([url]) => new URL(url, 'http://x').searchParams.get('scope'))
    expect(scopes).toEqual(['all', 'trash'])
  })

  it('offers no changes where the item cannot be changed', async () => {
    answerListings([SQUID, KRILL])
    const wrapper = section(WHALES, false)
    await flushPromises()

    expect(wrapper.findAll('.related__item')).toHaveLength(2)
    expect(wrapper.find('[aria-label="Add Related"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Remove Related"]').exists()).toBe(false)
  })

  it('is not drawn when there is nothing related and nothing to add', async () => {
    const wrapper = section(book('DDDD2345', 'Plankton'), false)
    await flushPromises()

    expect(wrapper.find('section').exists()).toBe(false)
    expect(requestMock).not.toHaveBeenCalled()
  })

  it('takes a link off both items with Remove Related', async () => {
    answerListings([SQUID, KRILL])
    const wrapper = section(WHALES)
    await flushPromises()
    requestMock.mockReset()
    requestMock.mockResolvedValue({ items: [] })

    await wrapper.findAll('[aria-label="Remove Related"]')[0].trigger('click')
    await flushPromises()

    expect(requestMock).toHaveBeenCalledWith(
      '/web/libraries/1/items/AAAA2345/related/CCCC2345',
      { method: 'DELETE' },
    )
  })

  it('finds an item to relate, leaving out this one and those already related', async () => {
    vi.useFakeTimers()
    const plankton = book('DDDD2345', 'Plankton')
    answerListings([SQUID, KRILL])
    const wrapper = section(WHALES)
    await flushPromises()

    await wrapper.find('[aria-label="Add Related"]').trigger('click')
    requestMock.mockImplementation(async (_url: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return { items: [] }
      return { items: [WHALES, SQUID, plankton] }
    })
    await wrapper.find('input[type="search"]').setValue('a')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(requestMock).toHaveBeenCalledWith(
      '/web/libraries/1/items?scope=all&q=a&sort=title&limit=20',
    )
    const offered = wrapper.findAll('.related__search .related__item')
    expect(offered.map((row) => row.find('.related__label').text())).toEqual(['Plankton'])

    await offered[0].trigger('click')
    await flushPromises()

    expect(requestMock).toHaveBeenCalledWith('/web/libraries/1/items/AAAA2345/related', {
      method: 'POST',
      body: { items: ['DDDD2345'] },
    })
    expect(wrapper.find('input[type="search"]').exists()).toBe(false)
  })

  it('says so when a search finds nothing', async () => {
    vi.useFakeTimers()
    const wrapper = section(book('DDDD2345', 'Plankton'))
    await flushPromises()
    await wrapper.find('[aria-label="Add Related"]').trigger('click')
    requestMock.mockResolvedValue({ items: [] })

    await wrapper.find('input[type="search"]').setValue('zzz')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(wrapper.find('[role="status"]').text()).toBe('No items match this search.')
  })

  it('closes the search on Escape', async () => {
    const wrapper = section(book('DDDD2345', 'Plankton'))
    await flushPromises()
    await wrapper.find('[aria-label="Add Related"]').trigger('click')

    await wrapper.find('input[type="search"]').trigger('keydown', { key: 'Escape' })

    expect(wrapper.find('input[type="search"]').exists()).toBe(false)
  })
})
