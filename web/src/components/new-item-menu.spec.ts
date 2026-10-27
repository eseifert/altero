import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { loadLabels, resetLabels, titleField } from '@/items/labels'
import { newItemMenu, RECENT_TYPES_KEY, recentTypes, rememberType } from '@/items/newitemtypes'

import NewItemMenu from './NewItemMenu.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const NAMES: Record<string, string> = {
  book: 'Book',
  bookSection: 'Book Section',
  journalArticle: 'Journal Article',
  newspaperArticle: 'Newspaper Article',
  document: 'Document',
  film: 'Film',
  case: 'Case',
  webpage: 'Web Page',
}

const label = (name: string) => NAMES[name] ?? name

beforeEach(async () => {
  setActivePinia(createPinia())
  localStorage.clear()
  resetLabels()
  requestMock.mockReset()
  requestMock.mockResolvedValue({
    itemTypes: NAMES,
    fields: {},
    creatorTypes: {},
    mappings: { case: { title: 'caseName' } },
    types: Object.fromEntries(Object.keys(NAMES).map((name) => [name, { fields: ['title'], creatorTypes: [] }])),
  })
  await loadLabels()
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('newItemMenu', () => {
  it('offers the desktop’s five defaults first when nothing has been made yet', () => {
    const { primary, all } = newItemMenu(Object.keys(NAMES), [], label, 'en-US')

    expect(primary).toEqual(['book', 'bookSection', 'document', 'journalArticle', 'newspaperArticle'])
    expect(all).toEqual(['book', 'bookSection', 'case', 'document', 'film', 'journalArticle', 'newspaperArticle'])
  })

  it('puts the types used last among the five, made up from the defaults', () => {
    const { primary } = newItemMenu(Object.keys(NAMES), ['film', 'case'], label, 'en-US')

    expect(primary).toEqual(['book', 'bookSection', 'case', 'film', 'journalArticle'])
  })

  it('never offers a web page, as the desktop leaves it to the Connector', () => {
    const { primary, all } = newItemMenu(Object.keys(NAMES), ['webpage'], label, 'en-US')

    expect(primary).not.toContain('webpage')
    expect(all).not.toContain('webpage')
  })
})

describe('recent types', () => {
  it('keeps the five used last, newest first', () => {
    for (const name of ['book', 'film', 'case', 'document', 'bookSection', 'film', 'journalArticle']) {
      rememberType(name)
    }

    expect(recentTypes()).toEqual(['journalArticle', 'film', 'bookSection', 'document', 'case'])
  })

  it('moves a type used again to the front rather than listing it twice', () => {
    for (const name of ['book', 'film', 'book']) rememberType(name)

    expect(recentTypes()).toEqual(['book', 'film'])
  })

  it('ignores what it cannot read', () => {
    localStorage.setItem(RECENT_TYPES_KEY, '{not json')

    expect(recentTypes()).toEqual([])
  })
})

describe('titleField', () => {
  it('names each type’s own title field', () => {
    expect(titleField('case')).toBe('caseName')
    expect(titleField('book')).toBe('title')
  })
})

describe('NewItemMenu', () => {
  it('lists the primary types, a separator, then every type', async () => {
    const wrapper = mount(NewItemMenu, { attachTo: document.body })

    await wrapper.find('[aria-label="New Item"]').trigger('click')

    const entries = wrapper.findAll('[role="menuitem"], [role="separator"]').map((entry) => entry.text() || '—')
    expect(entries).toEqual([
      'Book', 'Book Section', 'Document', 'Journal Article', 'Newspaper Article', '—',
      'Book', 'Book Section', 'Case', 'Document', 'Film', 'Journal Article', 'Newspaper Article',
    ])
    expect(document.activeElement?.textContent?.trim()).toBe('Book')
  })

  it('says which type was chosen, and remembers it', async () => {
    const wrapper = mount(NewItemMenu, { attachTo: document.body })
    await wrapper.find('[aria-label="New Item"]').trigger('click')

    await wrapper.findAll('[role="menuitem"]').find((entry) => entry.text() === 'Film')!.trigger('click')

    expect(wrapper.emitted('create')).toEqual([['film']])
    expect(recentTypes()).toEqual(['film'])
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  })

  it('moves with the arrow keys and closes on Escape', async () => {
    const wrapper = mount(NewItemMenu, { attachTo: document.body })
    await wrapper.find('[aria-label="New Item"]').trigger('click')
    const menu = wrapper.find('[role="menu"]')

    await menu.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement?.textContent?.trim()).toBe('Book Section')
    await menu.trigger('keydown', { key: 'ArrowUp' })
    await menu.trigger('keydown', { key: 'ArrowUp' })
    expect(document.activeElement?.textContent?.trim()).toBe('Newspaper Article')

    await menu.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement?.getAttribute('aria-label')).toBe('New Item')
  })
})
