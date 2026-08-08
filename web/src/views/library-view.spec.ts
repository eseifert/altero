import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { resetLabels } from '@/items/labels'
import {
  SIDEBAR_DEFAULT,
  SIDEBAR_MAX,
  SIDEBAR_MIN,
  SIDEBAR_STORAGE_KEY,
} from '@/sidebarwidth'
import { useLibraryStore } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

import LibraryView from './LibraryView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const PERSONAL = {
  id: 1,
  type: 'user',
  ownerId: 1,
  name: 'Ada',
  version: 4,
  prefix: '/users/1',
  writable: true,
}
const GROUP = {
  id: 7,
  type: 'group',
  ownerId: 7,
  name: 'Whale Watchers',
  version: 2,
  prefix: '/groups/7',
  // A group that reserves editing for its administrators, which is what makes
  // it the interesting one: the controls must not be offered here.
  writable: false,
}

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

const NESTED = {
  key: 'DDDD2345',
  version: 1,
  data: { key: 'DDDD2345', name: 'Humpbacks', parentCollection: 'CCCC2345' },
  meta: { numCollections: 0, numItems: 0 },
}

const OTHER = {
  key: 'EEEE2345',
  version: 1,
  data: { key: 'EEEE2345', name: 'Dolphins', parentCollection: false },
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
  const current = above?.querySelector('.library__library--current')
  if (!current) return null
  return (current.textContent ?? '').replace(/\s+/g, ' ').trim()
}

describe('the library nav', () => {
  it('names the library even when it is the only one', async () => {
    /* It used to be left out here, on the grounds that one library needs no
       hierarchy. A personal library carries the account's own name, so the row
       reads "Ada" rather than "My Library" over "My library" -- and it is the
       row the collections hang from, and the row a collection is added on. */
    const wrapper = await open()

    expect(sidebar(wrapper)).toEqual(['Ada', 'My library', 'Everything', 'Trash'])
    expect(viewsBelongTo(wrapper)).toBe('Ada')
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

describe('making and removing collections', () => {
  /** Answer the tree with `collections`, and let a write succeed. */
  function withCollections(collections: unknown[], write?: (path: string) => Promise<unknown>) {
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method && options.method !== 'GET') {
        return write ? write(path) : Promise.resolve(COLLECTION)
      }
      if (path === '/web/libraries') return Promise.resolve(libraries)
      if (path.startsWith('/web/schema')) {
        return Promise.resolve({ itemTypes: {}, fields: {}, creatorTypes: {} })
      }
      if (path.includes('/collections')) return Promise.resolve({ collections })
      if (path.includes('/tags')) return Promise.resolve({ tags: [] })
      if (path.includes('/children')) return Promise.resolve({ items: [] })
      return Promise.resolve({ total: contents.length, items: contents })
    })
  }

  /**
   * Click the sidebar row for `name`.
   *
   * Driven through the interface rather than by reaching for the store: the
   * component holds a store of its own, and a test that calls `useStore()`
   * halfway through can be handed a different one -- an earlier test's Pinia
   * can still be the active one when a leftover request of its own resolves.
   * Clicking the row is what a reader does anyway.
   */
  function openCollection(wrapper: ReturnType<typeof mount>, name: string) {
    const row = wrapper.findAll('.tree__name').find((entry) => entry.text().includes(name))
    if (!row) throw new Error(`No collection row for ${name}`)
    return row.trigger('click')
  }

  /** The library's own plus, on the row that stands for its top level. */
  function libraryAction(wrapper: ReturnType<typeof mount>) {
    return wrapper.get('.library__action')
  }

  /** The plus or the cross on the row for `name`. */
  function rowAction(
    wrapper: ReturnType<typeof mount>,
    name: string,
    action: 'add' | 'remove',
  ) {
    const label = action === 'add' ? `New subcollection inside “${name}”` : `Delete “${name}”`
    return wrapper.get(`[aria-label="${label}"]`)
  }

  /** The calls that changed something. */
  function writes() {
    return requestMock.mock.calls.filter(
      ([, options]) => options && options.method && options.method !== 'GET',
    )
  }

  it('offers to make one in a library with none, which is where it is needed most', async () => {
    const wrapper = await open()

    expect(wrapper.find('.library__action').exists()).toBe(true)
    expect(wrapper.find('.tree').exists()).toBe(false)
  })

  it('puts the plus on the row naming the library, not on a view below it', async () => {
    /* That row is what the collections hang from, so it is the row a
       collection is added on. */
    withCollections([COLLECTION])
    const wrapper = await open()

    const row = libraryAction(wrapper).element.closest('.library__nav-row')
    expect(row?.querySelector('.library__library')?.textContent).toContain('Ada')
  })

  it('offers it only on the library being read', async () => {
    /* The tree below belongs to that one; a plus on another library would
       write to something nothing on screen is showing. */
    libraries = [PERSONAL, { ...GROUP, writable: true }]
    withCollections([COLLECTION])
    const wrapper = await open()

    expect(wrapper.findAll('.library__action')).toHaveLength(1)
    const row = wrapper.get('.library__action').element.closest('.library__nav-row')
    expect(row?.querySelector('.library__library')?.textContent).toContain('Ada')
  })

  it('puts the library’s plus where a collection’s is, and calls it the same', async () => {
    /* Two controls that do the same thing at two levels of one list. */
    withCollections([COLLECTION])
    const wrapper = await open()

    expect(libraryAction(wrapper).attributes('aria-label')).toBe('New collection')
    expect(rowAction(wrapper, 'Whales', 'add').attributes('aria-label')).toBe(
      'New subcollection inside “Whales”',
    )
  })

  it('offers nothing of the sort in a library that may only be read', async () => {
    /* Whether this account may write is the server's answer, and a control the
       server will refuse is a control not to draw. */
    libraries = [PERSONAL, GROUP]
    withCollections([COLLECTION])
    const wrapper = await open()
    await wrapper.findAll('.library__library')[1].trigger('click')
    await settle(wrapper)

    expect(wrapper.find('.library__action').exists()).toBe(false)
    expect(wrapper.findAll('.tree__action')).toHaveLength(0)
  })

  it('lists the collections with the views, as one hierarchy under the library', async () => {
    /* A collection is another thing the library can be narrowed to, not a
       separate kind of place, and there is no heading saying otherwise. */
    withCollections([COLLECTION])
    const wrapper = await open()

    const rows = wrapper.get('.library__scopes').findAll('.library__label, .tree__label')
    expect(rows.map((row) => row.text())).toEqual(['My library', 'Everything', 'Trash', 'Whales'])
  })

  it('opens a dialog rather than a field on its own', async () => {
    /* Where it goes is half of what making one takes, and a field alone says
       nothing about that. */
    withCollections([])
    const wrapper = await open()

    await libraryAction(wrapper).trigger('click')

    expect(wrapper.get('dialog').element.open).toBe(true)
    expect(wrapper.get('.dialog__where').text()).toContain('Created in')
  })

  it('names the library it will be made in', async () => {
    withCollections([])
    const wrapper = await open()

    await libraryAction(wrapper).trigger('click')

    expect(wrapper.get('.dialog__path').text()).toContain('Ada')
  })

  it('shows the path down to the row the plus was pressed on', async () => {
    /* This is the whole point of the dialog: "here" is a place in a tree, and
       the tree is where it has to be shown. */
    withCollections([COLLECTION, NESTED])
    const wrapper = await open()
    await wrapper.get('.tree__twisty').trigger('click')

    await rowAction(wrapper, 'Humpbacks', 'add').trigger('click')

    const steps = wrapper.findAll('.dialog__step-name').map((step) => step.text())
    expect(steps).toEqual(['Ada', 'Whales', 'Humpbacks'])
  })

  it('sends the name that was typed', async () => {
    withCollections([])
    const wrapper = await open()

    await libraryAction(wrapper).trigger('click')
    await wrapper.get('.dialog__field').setValue('Papers')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(writes()).toEqual([
      ['/web/libraries/1/collections', { method: 'POST', body: { name: 'Papers' } }],
    ])
  })

  it('makes one at the top level whatever is open, because the row says so', async () => {
    /* The plus belongs to the library's row, so it means that row -- not
       wherever the reader happens to have clicked. */
    withCollections([COLLECTION])
    const wrapper = await open()
    await openCollection(wrapper, 'Whales')
    await settle(wrapper)

    await libraryAction(wrapper).trigger('click')
    await wrapper.get('.dialog__field').setValue('Papers')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(writes()[0][1]).toEqual({ method: 'POST', body: { name: 'Papers' } })
  })

  it('sends the parent when the row asked for a subcollection', async () => {
    /* The plus on a row acts on that row, whether or not it is the selected
       one -- otherwise it would be the same control twice. */
    withCollections([COLLECTION, OTHER])
    const wrapper = await open()
    await openCollection(wrapper, 'Dolphins')
    await settle(wrapper)

    await rowAction(wrapper, 'Whales', 'add').trigger('click')
    await wrapper.get('.dialog__field').setValue('Drafts')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(writes()[0][1]).toEqual({
      method: 'POST',
      body: { name: 'Drafts', parentCollection: 'CCCC2345' },
    })
  })

  it('says which collection it is about to make one inside', async () => {
    withCollections([COLLECTION])
    const wrapper = await open()

    await rowAction(wrapper, 'Whales', 'add').trigger('click')

    expect(wrapper.get('.dialog__path').text()).toContain('Whales')
  })

  it('closes without writing when the dialog is dismissed', async () => {
    withCollections([])
    const wrapper = await open()
    await libraryAction(wrapper).trigger('click')

    await wrapper.findAll('.dialog__actions button')[0].trigger('click')
    await settle(wrapper)

    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(writes()).toEqual([])
  })

  it('refuses an empty name without asking the server', async () => {
    withCollections([])
    const wrapper = await open()

    await libraryAction(wrapper).trigger('click')
    await wrapper.get('.dialog__field').setValue('   ')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(writes()).toEqual([])
    expect(wrapper.get('.dialog__error').text()).toContain('A collection needs a name.')
  })

  it('asks before removing one, and does nothing until answered', async () => {
    withCollections([COLLECTION])
    const wrapper = await open()

    await rowAction(wrapper, 'Whales', 'remove').trigger('click')

    expect(wrapper.get('.collections__confirm').text()).toContain('Whales')
    expect(writes()).toEqual([])
  })

  it('removes it once that is confirmed', async () => {
    withCollections([COLLECTION], () => Promise.resolve(null))
    const wrapper = await open()
    await rowAction(wrapper, 'Whales', 'remove').trigger('click')

    await wrapper.findAll('.collections__confirm button')[1].trigger('click')
    await settle(wrapper)

    expect(writes()).toEqual([
      ['/web/libraries/1/collections/CCCC2345', { method: 'DELETE' }],
    ])
  })

  it('leaves it alone when the question is dismissed', async () => {
    withCollections([COLLECTION])
    const wrapper = await open()
    await rowAction(wrapper, 'Whales', 'remove').trigger('click')

    await wrapper.findAll('.collections__confirm button')[0].trigger('click')
    await settle(wrapper)

    expect(writes()).toEqual([])
    expect(wrapper.find('.collections__confirm').exists()).toBe(false)
  })

  it('reports a refusal in the dialog, which stays open with the name in it', async () => {
    withCollections([], () => Promise.reject(new Error('You cannot change this library')))
    const wrapper = await open()

    await libraryAction(wrapper).trigger('click')
    await wrapper.get('.dialog__field').setValue('Papers')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(wrapper.get('.dialog__error').text()).toContain('You cannot change this library')
    expect((wrapper.get('.dialog__field').element as HTMLInputElement).value).toBe('Papers')
    expect(wrapper.find('.library__state--error').exists()).toBe(false)
  })
})

describe('renaming a tag', () => {
  const TAGS = [
    { tag: 'ficton', type: 0, numItems: 2 },
    { tag: 'whales', type: 0, numItems: 1 },
  ]

  /** Answer the tag panel with `tags`, and let the rename do `write`. */
  function withTags(tags: unknown[], write?: (path: string) => Promise<unknown>) {
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method && options.method !== 'GET') {
        return write
          ? write(path)
          : Promise.resolve({ tag: 'fiction', type: 0, numItems: 2, itemsChanged: 2 })
      }
      if (path === '/web/libraries') return Promise.resolve(libraries)
      if (path.startsWith('/web/schema')) {
        return Promise.resolve({ itemTypes: {}, fields: {}, creatorTypes: {} })
      }
      if (path.includes('/collections')) return Promise.resolve({ collections: [] })
      if (path.includes('/tags')) return Promise.resolve({ tags })
      if (path.includes('/children')) return Promise.resolve({ items: [] })
      return Promise.resolve({ total: contents.length, items: contents })
    })
  }

  /** The pencil on the pill for `name`. */
  function pencil(wrapper: ReturnType<typeof mount>, name: string) {
    return wrapper.get(`[aria-label="Rename “${name}”"]`)
  }

  /** The calls that changed something. */
  function writes() {
    return requestMock.mock.calls.filter(
      ([, options]) => options && options.method && options.method !== 'GET',
    )
  }

  it('offers a rename on every tag', async () => {
    withTags(TAGS)
    const wrapper = await open()

    expect(wrapper.findAll('.library__tag-action')).toHaveLength(2)
  })

  it('offers nothing of the sort in a library that may only be read', async () => {
    libraries = [GROUP]
    withTags(TAGS)
    const wrapper = await open()

    expect(wrapper.findAll('.library__tag')).toHaveLength(2)
    expect(wrapper.find('.library__tag-action').exists()).toBe(false)
  })

  it('opens a dialog holding the name the tag has', async () => {
    withTags(TAGS)
    const wrapper = await open()

    await pencil(wrapper, 'ficton').trigger('click')

    expect((wrapper.get('.dialog__field').element as HTMLInputElement).value).toBe('ficton')
    expect(writes()).toEqual([])
  })

  it('says what renaming will do, and to how many items', async () => {
    withTags(TAGS)
    const wrapper = await open()

    await pencil(wrapper, 'ficton').trigger('click')

    expect(wrapper.get('.dialog__note').text()).toContain('all associated items')
    expect(wrapper.get('.dialog__note').text()).toContain('2 items')
  })

  it('sends the name that was typed', async () => {
    withTags(TAGS)
    const wrapper = await open()
    await pencil(wrapper, 'ficton').trigger('click')

    await wrapper.get('.dialog__field').setValue('fiction')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(writes()).toEqual([
      ['/web/libraries/1/tags/ficton', { method: 'PATCH', body: { tag: 'fiction' } }],
    ])
    expect(wrapper.find('dialog').exists()).toBe(false)
  })

  it('refuses an empty name without asking the server', async () => {
    withTags(TAGS)
    const wrapper = await open()
    await pencil(wrapper, 'ficton').trigger('click')

    await wrapper.get('.dialog__field').setValue('   ')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(writes()).toEqual([])
    expect(wrapper.get('.dialog__error').text()).toContain('A tag needs a name.')
  })

  it('closes without writing when the dialog is dismissed', async () => {
    withTags(TAGS)
    const wrapper = await open()
    await pencil(wrapper, 'ficton').trigger('click')

    await wrapper.findAll('.dialog__actions button')[0].trigger('click')
    await settle(wrapper)

    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(writes()).toEqual([])
  })

  it('reports a refusal in the dialog, which stays open with the name in it', async () => {
    withTags(TAGS, () => Promise.reject(new Error('You cannot change this library')))
    const wrapper = await open()
    await pencil(wrapper, 'ficton').trigger('click')

    await wrapper.get('.dialog__field').setValue('fiction')
    await wrapper.get('.dialog__body').trigger('submit')
    await settle(wrapper)

    expect(wrapper.get('.dialog__error').text()).toContain('You cannot change this library')
    expect((wrapper.get('.dialog__field').element as HTMLInputElement).value).toBe('fiction')
    expect(wrapper.find('.library__state--error').exists()).toBe(false)
  })
})

/**
 * The width of the sidebar.
 *
 * A tree is as wide as whoever built it made it, so the column has to be the
 * reader's to set -- and having set it, they should not have to set it again
 * on the next visit. Everything here also has to work without a pointer,
 * which is what the arrow keys are for.
 */
describe('the sidebar width', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  /** The width the grid is currently laid out at, in pixels. */
  function width(wrapper: ReturnType<typeof mount>): number {
    const style = wrapper.get('.library').attributes('style') ?? ''
    return Number(/--sidebar-width:\s*(\d+)px/.exec(style)?.[1])
  }

  function grip(wrapper: ReturnType<typeof mount>) {
    return wrapper.get('[role="separator"]')
  }

  /* Dispatched rather than triggered: the wrapper's `trigger` assigns the
     properties after constructing the event, and `clientX` is read-only. */
  function drag(wrapper: ReturnType<typeof mount>, from: number, to: number): void {
    grip(wrapper).element.dispatchEvent(
      new MouseEvent('pointerdown', { clientX: from, bubbles: true }),
    )
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: to }))
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: to }))
  }

  /** Let the pause the writing waits out expire. */
  async function stored(): Promise<string | null> {
    await new Promise((resolve) => setTimeout(resolve, 300))
    return localStorage.getItem(SIDEBAR_STORAGE_KEY)
  }

  it('starts at the default when nothing has been chosen', async () => {
    const wrapper = await open()

    expect(width(wrapper)).toBe(SIDEBAR_DEFAULT)
  })

  it('starts at the remembered width', async () => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, '320')

    const wrapper = await open()

    expect(width(wrapper)).toBe(320)
  })

  it('falls back to the default rather than failing on nonsense', async () => {
    /* A convenience must not be able to stop the library from being drawn. */
    localStorage.setItem(SIDEBAR_STORAGE_KEY, 'as wide as a barn')

    const wrapper = await open()

    expect(width(wrapper)).toBe(SIDEBAR_DEFAULT)
  })

  it('follows a drag, and remembers where it was let go', async () => {
    const wrapper = await open()

    drag(wrapper, 300, 360)
    await wrapper.vm.$nextTick()

    expect(width(wrapper)).toBe(SIDEBAR_DEFAULT + 60)
    expect(await stored()).toBe(String(SIDEBAR_DEFAULT + 60))
  })

  it('stops following once the pointer is let go', async () => {
    const wrapper = await open()

    grip(wrapper).element.dispatchEvent(
      new MouseEvent('pointerdown', { clientX: 300, bubbles: true }),
    )
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 300 }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 900 }))
    await wrapper.vm.$nextTick()

    expect(width(wrapper)).toBe(SIDEBAR_DEFAULT)
  })

  it('moves with the arrow keys, so a pointer is not the only way', async () => {
    const wrapper = await open()

    await grip(wrapper).trigger('keydown', { key: 'ArrowRight' })
    await grip(wrapper).trigger('keydown', { key: 'ArrowRight' })
    await grip(wrapper).trigger('keydown', { key: 'ArrowLeft' })

    expect(width(wrapper)).toBe(SIDEBAR_DEFAULT + 16)
    expect(await stored()).toBe(String(SIDEBAR_DEFAULT + 16))
  })

  it('goes no narrower than the tree can be read in, and no wider than the window', async () => {
    const wrapper = await open()

    await grip(wrapper).trigger('keydown', { key: 'Home' })
    expect(width(wrapper)).toBe(SIDEBAR_MIN)

    drag(wrapper, 300, -400)
    await wrapper.vm.$nextTick()
    expect(width(wrapper)).toBe(SIDEBAR_MIN)

    await grip(wrapper).trigger('keydown', { key: 'End' })
    expect(width(wrapper)).toBe(SIDEBAR_MAX)
  })

  it('goes back to the default on a double-click', async () => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, '400')
    const wrapper = await open()

    await grip(wrapper).trigger('dblclick')

    expect(width(wrapper)).toBe(SIDEBAR_DEFAULT)
    expect(await stored()).toBe(String(SIDEBAR_DEFAULT))
  })

  it('says what it is and where it stands, for anything that cannot see it', async () => {
    const wrapper = await open()

    expect(grip(wrapper).attributes('aria-orientation')).toBe('vertical')
    expect(grip(wrapper).attributes('aria-label')).toBe('Sidebar width')
    expect(grip(wrapper).attributes('aria-valuenow')).toBe(String(SIDEBAR_DEFAULT))
    expect(grip(wrapper).attributes('aria-valuemin')).toBe(String(SIDEBAR_MIN))
    expect(grip(wrapper).attributes('aria-valuemax')).toBe(String(SIDEBAR_MAX))
  })
})
