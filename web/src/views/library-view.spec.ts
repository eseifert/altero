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

const PERSONAL = { id: 1, type: 'user', ownerId: 1, name: 'Ada', version: 4, prefix: '/users/1' }
const GROUP = { id: 7, type: 'group', ownerId: 7, name: 'Whale Watchers', version: 2, prefix: '/groups/7' }

/** What `/web/libraries` answers. A test that needs a group to switch to widens it. */
let libraries: unknown[] = [PERSONAL]

const ITEM = {
  key: 'AAAA2345',
  version: 1,
  data: { itemType: 'book', title: 'Structure and Interpretation' },
  meta: {},
}

/** What the item request answers. A test about the empty list empties it. */
let contents: unknown[] = [ITEM]

const COLLECTION = {
  key: 'CCCC2345',
  version: 1,
  data: { key: 'CCCC2345', name: 'Whales', parentCollection: false },
  meta: { numCollections: 0, numItems: 0 },
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
  libraries = [PERSONAL]
  contents = [ITEM]
  requestMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/libraries') return Promise.resolve(libraries)
    if (path.startsWith('/web/schema')) {
      return Promise.resolve({ itemTypes: {}, fields: {}, creatorTypes: {} })
    }
    if (path.includes('/collections')) return Promise.resolve({ collections: [] })
    if (path.includes('/tags')) return Promise.resolve({ tags: [] })
    if (path.includes('/children')) return Promise.resolve({ items: [] })
    return Promise.resolve({ total: contents.length, items: contents })
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

/**
 * What the list says when it has nothing to show.
 *
 * The empty state is the one place the interface volunteers advice, and the
 * advice is only right for one of the several reasons a list can be empty.
 */
describe('an empty list', () => {
  const SYNC = 'Nothing here yet. Point the Zotero desktop app at this server and sync.'

  function state(wrapper: ReturnType<typeof mount>): string {
    return wrapper.get('.library__state').text()
  }

  it('tells an untouched library how to get something into it', async () => {
    contents = []

    const wrapper = await open()

    expect(state(wrapper)).toBe(SYNC)
  })

  it('does not tell somebody whose search found nothing to go and sync', async () => {
    /* The library has been synced -- that is why there is something to search
       -- so the advice reads as though the sync had not worked. */
    const wrapper = await open()
    contents = []

    await useLibraryStore().setSearch('narwhal')
    await settle(wrapper)

    expect(state(wrapper)).toBe('No items match this search.')
  })

  it('blames the tags when the tags are what emptied it', async () => {
    const wrapper = await open()
    contents = []

    await useLibraryStore().toggleTag('cetacea')
    await settle(wrapper)

    expect(state(wrapper)).toBe('No items carry the selected tags.')
  })

  it('names both when a search and a tag are in force', async () => {
    /* Clearing either one on its own may still leave the list empty, so a
       message naming only one of them sends the reader the wrong way. */
    const wrapper = await open()
    contents = []
    const store = useLibraryStore()

    await store.setSearch('narwhal')
    await store.toggleTag('cetacea')
    await settle(wrapper)

    expect(state(wrapper)).toBe('No items match this search and the selected tags.')
  })

  it('says an empty collection is empty', async () => {
    const usual = requestMock.getMockImplementation()!
    requestMock.mockImplementation((path: string) =>
      path.includes('/collections') ? Promise.resolve({ collections: [COLLECTION] }) : usual(path),
    )
    const wrapper = await open()
    contents = []

    await wrapper.get('.tree__name').trigger('click')
    await settle(wrapper)

    expect(state(wrapper)).toBe('This collection is empty.')
  })

  it('says the trash is empty', async () => {
    const wrapper = await open()
    contents = []

    await useLibraryStore().selectScope('trash')
    await settle(wrapper)

    expect(state(wrapper)).toBe('The trash is empty.')
  })

  it('does not send a group’s members off to sync their own libraries', async () => {
    /* A group fills up when a member syncs into it, which may well be somebody
       other than whoever is reading this, and may be nobody who can. */
    libraries = [PERSONAL, GROUP]
    contents = []
    const wrapper = await open()

    await wrapper.findAll('.library__library')[1].trigger('click')
    await settle(wrapper)

    expect(state(wrapper)).toBe('Nothing has been added to this group yet.')
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

/** Every row of the library nav, in the order the column shows them. */
function sidebar(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('.library__library, .library__scope').map((row) => row.text())
}

/**
 * The library the views are drawn inside, by name, or null if they stand on
 * their own. Order alone cannot tell the two arrangements apart -- a flat list
 * ending in the views looks the same as the views nested under the last
 * library -- so this asks the DOM which row they hang from.
 */
function viewsBelongTo(wrapper: ReturnType<typeof mount>): string | null {
  const scopes = wrapper.find('.library__scopes--nested')
  if (!scopes.exists()) return null
  const above = scopes.element.previousElementSibling
  if (!above?.classList.contains('library__library--current')) return null
  return (above.textContent ?? '').replace(/\s+/g, ' ').trim()
}

describe('the library nav', () => {
  it('names no library when there is only one, and leaves the views flush', async () => {
    /* The row would say "My Library" directly above "My library", and there is
       no hierarchy to draw when nothing else can be picked. */
    const wrapper = await open()

    expect(sidebar(wrapper)).toEqual(['My library', 'Everything', 'Trash'])
    expect(viewsBelongTo(wrapper)).toBeNull()
  })

  it('draws the views inside the library they act on', async () => {
    libraries = [PERSONAL, GROUP]

    const wrapper = await open()

    expect(sidebar(wrapper)).toEqual([
      'Ada',
      'My library',
      'Everything',
      'Trash',
      'Whale Watchers',
    ])
    expect(viewsBelongTo(wrapper)).toBe('Ada')
  })

  it('takes them along when another library is opened', async () => {
    /* This is what the nesting is for: "Trash" under a group is that group's
       trash, and one Trash above a list of libraries said otherwise. */
    libraries = [PERSONAL, GROUP]
    const wrapper = await open()

    await wrapper.findAll('.library__library')[1].trigger('click')
    await settle(wrapper)

    expect(sidebar(wrapper)).toEqual([
      'Ada',
      'Whale Watchers',
      'My library',
      'Everything',
      'Trash',
    ])
    expect(viewsBelongTo(wrapper)).toBe('Whale Watchers')
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
