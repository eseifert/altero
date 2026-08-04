import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fieldLabel, humanize, itemTypeLabel, loadLabels, resetLabels } from '@/items/labels'
import type { CollectionNode, ItemEnvelope } from '@/stores/library'

import CollectionTree from './CollectionTree.vue'
import ItemDetail from './ItemDetail.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

function node(key: string, name: string, children: CollectionNode[] = []): CollectionNode {
  return {
    key,
    version: 1,
    data: { key, name, parentCollection: false },
    meta: { numCollections: children.length, numItems: 2 },
    children,
  }
}

const ARTICLE: ItemEnvelope = {
  key: 'AAAA2345',
  version: 3,
  data: {
    itemType: 'journalArticle',
    title: 'A study of things',
    publicationTitle: 'Journal of Things',
    DOI: '10.1000/xyz',
    creators: [{ creatorType: 'author', firstName: 'Jane', lastName: 'Doe' }],
    tags: [{ tag: 'toread' }],
  },
  meta: { creatorSummary: 'Doe', parsedDate: '2019' },
}

function detail(item: ItemEnvelope = ARTICLE, children: ItemEnvelope[] = []) {
  return mount(ItemDetail, {
    props: {
      item,
      children,
      libraryId: 1,
      fileUrl: (key: string, options?: { download?: boolean }) =>
        `/web/libraries/1/items/${key}/file${options?.download ? '?download=true' : ''}`,
    },
  })
}

beforeEach(() => {
  requestMock.mockReset()
  resetLabels()
})

describe('CollectionTree', () => {
  it('lists the collections it is given', () => {
    const wrapper = mount(CollectionTree, {
      props: { nodes: [node('AAAA2345', 'Papers'), node('BBBB2345', 'Books')], selected: null },
    })

    expect(wrapper.text()).toContain('Papers')
    expect(wrapper.text()).toContain('Books')
  })

  it('hides children until the branch is expanded', async () => {
    const wrapper = mount(CollectionTree, {
      props: {
        nodes: [node('AAAA2345', 'Papers', [node('BBBB2345', 'Drafts')])],
        selected: null,
      },
    })

    expect(wrapper.text()).not.toContain('Drafts')

    await wrapper.get('.tree__twisty').trigger('click')

    expect(wrapper.text()).toContain('Drafts')
  })

  it('emits the key that was clicked', async () => {
    const wrapper = mount(CollectionTree, {
      props: { nodes: [node('AAAA2345', 'Papers')], selected: null },
    })

    await wrapper.get('.tree__name').trigger('click')

    expect(wrapper.emitted('select')).toEqual([['AAAA2345']])
  })

  it('marks the selected collection for assistive technology too', () => {
    const wrapper = mount(CollectionTree, {
      props: { nodes: [node('AAAA2345', 'Papers')], selected: 'AAAA2345' },
    })

    expect(wrapper.get('.tree__name').attributes('aria-current')).toBe('true')
  })

  it('emits from a nested collection as well as a top-level one', async () => {
    const wrapper = mount(CollectionTree, {
      props: {
        nodes: [node('AAAA2345', 'Papers', [node('BBBB2345', 'Drafts')])],
        selected: null,
      },
    })
    await wrapper.get('.tree__twisty').trigger('click')

    await wrapper.findAll('.tree__name')[1].trigger('click')

    expect(wrapper.emitted('select')).toEqual([['BBBB2345']])
  })
})

describe('ItemDetail', () => {
  it('shows the fields an item has', () => {
    const wrapper = detail()

    expect(wrapper.text()).toContain('A study of things')
    expect(wrapper.text()).toContain('Journal of Things')
    expect(wrapper.text()).toContain('Doe')
  })

  it('links a DOI to where it resolves', () => {
    const link = detail()
      .findAll('a')
      .find((anchor) => anchor.text() === '10.1000/xyz')

    expect(link?.attributes('href')).toBe('https://doi.org/10.1000/xyz')
  })

  it('shows an imported attachment as something to open', () => {
    const attachment: ItemEnvelope = {
      key: 'BBBB2345',
      version: 1,
      data: { itemType: 'attachment', linkMode: 'imported_file', title: 'Scan', filename: 's.pdf' },
      meta: {},
    }

    const hrefs = detail(attachment)
      .findAll('a')
      .map((anchor) => anchor.attributes('href'))

    expect(hrefs).toContain('/web/libraries/1/items/BBBB2345/file')
    expect(hrefs).toContain('/web/libraries/1/items/BBBB2345/file?download=true')
  })

  it('offers nothing to open for a linked URL attachment, which has no bytes here', () => {
    const linked: ItemEnvelope = {
      key: 'BBBB2345',
      version: 1,
      data: { itemType: 'attachment', linkMode: 'linked_url', title: 'A page' },
      meta: {},
    }

    expect(detail(linked).text()).not.toContain('Download')
  })

  it('renders a citation from the server rather than making one up', async () => {
    requestMock.mockResolvedValue({ bib: '<div class="csl-bib-body">Doe, J. (2019).</div>' })
    const wrapper = detail()

    await wrapper.get('.detail__button').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(requestMock).toHaveBeenCalledWith(
      expect.stringContaining('/web/libraries/1/items/AAAA2345/citation?style='),
    )
    expect(wrapper.get('.detail__bib').text()).toContain('Doe, J. (2019).')
  })

  it('drops a rendered citation when another item is selected', async () => {
    /* Otherwise the previous item's citation sits under the new item's title. */
    requestMock.mockResolvedValue({ bib: '<div>Doe, J. (2019).</div>' })
    const wrapper = detail()
    await wrapper.get('.detail__button').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    await wrapper.setProps({
      item: { ...ARTICLE, key: 'CCCC2345', data: { ...ARTICLE.data, title: 'Another' } },
    })

    expect(wrapper.find('.detail__bib').exists()).toBe(false)
  })

  it('shows a note as text rather than as a field list', () => {
    const note: ItemEnvelope = {
      key: 'CCCC2345',
      version: 1,
      data: { itemType: 'note', note: '<p>A thought</p>' },
      meta: {},
    }

    const wrapper = detail(note)

    expect(wrapper.get('.detail__note').text()).toBe('A thought')
  })

  it('lists child attachments and lets one be opened', async () => {
    const child: ItemEnvelope = {
      key: 'DDDD2345',
      version: 1,
      data: { itemType: 'attachment', linkMode: 'imported_file', title: 'PDF', filename: 'x.pdf' },
      meta: {},
    }
    const wrapper = detail(ARTICLE, [child])

    await wrapper.get('.detail__child').trigger('click')

    expect(wrapper.emitted('open')).toEqual([[child]])
  })
})

describe('labels', () => {
  it('splits a camel case field name when the schema has not loaded', () => {
    expect(humanize('publicationTitle')).toBe('Publication Title')
    expect(fieldLabel('numPages')).toBe('Num Pages')
  })

  it('prefers the schema’s own name once it is loaded', async () => {
    requestMock.mockResolvedValue({
      itemTypes: { journalArticle: 'Journal Article' },
      fields: { numPages: '# of Pages' },
      creatorTypes: { bookAuthor: 'Book Author' },
    })

    await loadLabels()

    expect(fieldLabel('numPages')).toBe('# of Pages')
    expect(fieldLabel('bookAuthor')).toBe('Book Author')
    expect(itemTypeLabel('journalArticle')).toBe('Journal Article')
  })

  it('asks the server once however many labels are wanted', async () => {
    requestMock.mockResolvedValue({ itemTypes: {}, fields: {}, creatorTypes: {} })

    await Promise.all([loadLabels(), loadLabels(), loadLabels()])

    expect(requestMock).toHaveBeenCalledTimes(1)
  })

  it('falls back rather than failing when the request does', async () => {
    requestMock.mockRejectedValue(new Error('offline'))

    await loadLabels()

    expect(fieldLabel('numPages')).toBe('Num Pages')
  })
})
