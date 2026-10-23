import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ItemDetail from '@/components/ItemDetail.vue'
import { i18n, setLocale } from '@/i18n'
import { loadLabels, resetLabels } from '@/items/labels'
import type { ItemEnvelope } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

import LibraryView from './LibraryView.vue'
import ProfileView from './ProfileView.vue'
import SharedView from './SharedView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const SCHEMA = {
  itemTypes: {},
  fields: {},
  creatorTypes: {},
  mappings: {
    case: { title: 'caseName' },
    email: { title: 'subject' },
    statute: { title: 'nameOfAct' },
  },
}

let item: ItemEnvelope

beforeEach(() => {
  setActivePinia(createPinia())
  resetLabels()
  i18n.global.locale.value = 'en-US'
  item = {
    key: 'AAAA2345',
    version: 1,
    data: { itemType: 'case', caseName: 'Example v. Example' },
    meta: {},
  }
  requestMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path.startsWith('/web/schema')) return Promise.resolve(SCHEMA)
    if (path === '/web/libraries') {
      return Promise.resolve([
        { id: 1, type: 'user', ownerId: 1, name: 'Ada', version: 1, prefix: '/users/1', writable: true },
      ])
    }
    if (path.includes('/collections')) return Promise.resolve({ collections: [] })
    if (path.includes('/tags')) return Promise.resolve({ tags: [] })
    if (path.includes('/items')) return Promise.resolve({ total: 1, items: [item] })
    if (path.startsWith('/web/profiles/')) {
      return Promise.resolve({
        username: 'ada', displayName: 'Ada', numPublications: 1, owner: false,
      })
    }
    if (path.startsWith('/web/shared/')) {
      return Promise.resolve({
        collection: 'Cases', library: 'Ada', numItems: 1,
        subcollections: false, files: false, expires: null,
      })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
})

describe.each([
  ['book', 'title'],
  ['case', 'caseName'],
  ['email', 'subject'],
  ['statute', 'nameOfAct'],
])('the title of an item of type %s', (itemType, field) => {
  beforeEach(() => {
    // There is deliberately no `title`: the API serves the type-specific field.
    item.data = { itemType, [field]: 'The title as entered in Zotero' }
  })

  it('appears in the library row and selected item heading', async () => {
    const wrapper = mount(LibraryView, { global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(wrapper.get('.library__cell--title').text()).toBe(item.data[field])
    await wrapper.get('.library__row:not(.library__row--head)').trigger('click')
    expect(wrapper.get('.detail__title').text()).toBe(item.data[field])
  })

  it('appears on a public profile', async () => {
    const wrapper = mount(ProfileView, {
      props: { username: 'ada' }, global: { stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.get('.publication__title').text()).toBe(item.data[field])
  })

  it('appears in a shared collection', async () => {
    const wrapper = mount(SharedView, { props: { token: 'example' } })
    await flushPromises()
    expect(wrapper.get('.entry__title').text()).toBe(item.data[field])
  })
})

it('keeps the translated fallback when the mapped title is empty', async () => {
  item.data.caseName = ''
  useLocaleStore().adopt({ language: 'de', timeZone: null })
  await setLocale('de')
  const wrapper = mount(LibraryView, { global: { stubs: { RouterLink: true } } })
  await flushPromises()
  expect(wrapper.get('.library__cell--title').text()).toBe('(ohne Titel)')
  await wrapper.get('.library__row:not(.library__row--head)').trigger('click')
  expect(wrapper.get('.detail__title').text()).toBe('(ohne Titel)')
})

it('updates an already rendered heading when schema mappings arrive', async () => {
  let answer!: (value: typeof SCHEMA) => void
  requestMock.mockImplementation(() => new Promise<typeof SCHEMA>((resolve) => {
    answer = resolve
  }))
  const wrapper = mount(ItemDetail, {
    props: { item, children: [], libraryId: 1, fileUrl: () => '' },
  })
  const loading = loadLabels()
  expect(wrapper.get('.detail__title').text()).toBe('(untitled)')

  answer(SCHEMA)
  await loading
  await flushPromises()

  expect(wrapper.get('.detail__title').text()).toBe('Example v. Example')
})
