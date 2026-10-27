import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { loadLabels, resetLabels } from '@/items/labels'
import type { ItemChanges, ItemEnvelope } from '@/stores/library'

import InfoPane from './InfoPane.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

/* A schema of two types, enough to tell the order of the fields from the
   order the item happens to list them in. */
const SCHEMA = {
  itemTypes: { book: 'Book', film: 'Film' },
  fields: { itemType: 'Item Type', title: 'Title', date: 'Date', abstractNote: 'Abstract', url: 'URL' },
  creatorTypes: {},
  mappings: {},
  types: {
    book: { fields: ['title', 'abstractNote', 'date', 'url', 'rights', 'edition'], creatorTypes: ['author'] },
    film: { fields: ['title', 'abstractNote', 'date', 'url', 'rights'], creatorTypes: ['director'] },
  },
}

const BOOK: ItemEnvelope = {
  key: 'AAAA2345',
  version: 3,
  data: {
    itemType: 'book',
    date: '26.10.2026',
    title: 'SICP',
    url: 'https://example.org/sicp',
    dateAdded: '2026-10-01T10:00:00Z',
  },
  meta: {},
}

beforeEach(async () => {
  setActivePinia(createPinia())
  requestMock.mockReset()
  resetLabels()
  requestMock.mockResolvedValue(SCHEMA)
  await loadLabels()
})

function pane(options: { editable?: boolean; save?: (changes: ItemChanges) => Promise<unknown> } = {}) {
  return mount(InfoPane, {
    props: { item: BOOK, editable: options.editable ?? true, save: options.save ?? vi.fn().mockResolvedValue(BOOK) },
    attachTo: document.body,
  })
}

function labels(wrapper: ReturnType<typeof pane>): string[] {
  return wrapper.findAll('dt').map((dt) => dt.text())
}

describe('InfoPane', () => {
  it('shows what an item says, in the schema’s order, where it cannot be changed', () => {
    const wrapper = pane({ editable: false })

    expect(labels(wrapper)).toEqual(['Item Type', 'Title', 'Date', 'URL', 'Date Added'])
    expect(wrapper.find('.info__value').exists()).toBe(false)
    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('shows every field of the type where it can, so an empty one can be filled', () => {
    const wrapper = pane()

    expect(labels(wrapper)).toEqual([
      'Item Type',
      'Title',
      'Abstract',
      'Date',
      'URL',
      'Rights',
      'Edition',
      'Date Added',
    ])
  })

  it('saves a field when Enter is pressed in it', async () => {
    const save = vi.fn().mockResolvedValue(BOOK)
    const wrapper = pane({ save })

    await wrapper.get('.info__value').trigger('click')
    const input = wrapper.get('textarea')
    await input.setValue('Structure and Interpretation')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ fields: { title: 'Structure and Interpretation' } })
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toBe('Saved.')
  })

  it('saves a field when it is left', async () => {
    const save = vi.fn().mockResolvedValue(BOOK)
    const wrapper = pane({ save })

    await wrapper.get('.info__value').trigger('click')
    await wrapper.get('textarea').setValue('Left behind')
    await wrapper.get('textarea').trigger('blur')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ fields: { title: 'Left behind' } })
  })

  it('puts a field back on Escape and saves nothing', async () => {
    const save = vi.fn()
    const wrapper = pane({ save })

    await wrapper.get('.info__value').trigger('click')
    await wrapper.get('textarea').setValue('Never mind')
    await wrapper.get('textarea').trigger('keydown', { key: 'Escape' })
    await flushPromises()

    expect(save).not.toHaveBeenCalled()
    expect(wrapper.get('.info__value').text()).toBe('SICP')
  })

  it('saves nothing for a field left as it was', async () => {
    const save = vi.fn()
    const wrapper = pane({ save })

    await wrapper.get('.info__value').trigger('click')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(save).not.toHaveBeenCalled()
  })

  it('takes a new line in the abstract, and saves it with Shift+Enter', async () => {
    const save = vi.fn().mockResolvedValue(BOOK)
    const wrapper = pane({ save })

    await wrapper.findAll('.info__value')[1].trigger('click')
    const box = wrapper.get('textarea')
    await box.setValue('One line\nand another')
    await box.trigger('keydown', { key: 'Enter' })
    expect(save).not.toHaveBeenCalled()

    await box.trigger('keydown', { key: 'Enter', shiftKey: true })
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ fields: { abstractNote: 'One line\nand another' } })
  })

  it('edits a URL like any field, and opens it from a button of its own', async () => {
    const wrapper = pane()

    const open = wrapper.get('a.info__open')
    expect(open.attributes('href')).toBe('https://example.org/sicp')
    expect(open.attributes('target')).toBe('_blank')
    await wrapper.get('#info-AAAA2345-url-value').trigger('click')

    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('https://example.org/sicp')
    expect(wrapper.find('a.info__open').exists()).toBe(false)
  })

  it('keeps a URL a plain link where nothing can be edited', () => {
    const wrapper = pane({ editable: false })

    expect(wrapper.get('dd a').attributes('href')).toBe('https://example.org/sicp')
    expect(wrapper.find('a.info__open').exists()).toBe(false)
  })

  it('opens a field at the height of the value it replaces', async () => {
    /* So that nothing around it moves; jsdom lays nothing out, so the height
       is the one the value is said to have. */
    const wrapper = pane()
    const shown = wrapper.get('#info-AAAA2345-abstractNote-value').element
    Object.defineProperty(shown, 'offsetHeight', { value: 57 })

    await wrapper.get('#info-AAAA2345-abstractNote-value').trigger('click')

    expect((wrapper.get('textarea').element as HTMLTextAreaElement).style.minHeight).toBe('57px')
  })

  it('takes a pasted line break in a field of one line as a space', async () => {
    const save = vi.fn().mockResolvedValue(BOOK)
    const wrapper = pane({ save })

    await wrapper.get('.info__value').trigger('click')
    await wrapper.get('textarea').setValue('Structure\nand Interpretation')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ fields: { title: 'Structure and Interpretation' } })
  })

  it('draws what the server stamps quieter than what can be edited', () => {
    const fixed = pane().findAll('dd.info__fixed')

    expect(fixed.map((dd) => dd.text())).toHaveLength(1)
    expect(pane({ editable: false }).find('dd.info__fixed').exists()).toBe(false)
  })

  it('says how Zotero reads the date', () => {
    const wrapper = pane()

    expect(wrapper.get('.info__order').text()).toBe('d m y')
  })

  it('says why a save was refused, at the field', async () => {
    const save = vi.fn().mockRejectedValue(new ApiError('The item has changed since you read it', 412))
    const wrapper = pane({ save })

    await wrapper.get('.info__value').trigger('click')
    await wrapper.get('textarea').setValue('Too late')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('The item has changed since you read it')
  })

  it('changes the type straight away when nothing would be lost', async () => {
    const save = vi.fn().mockResolvedValue(BOOK)
    const wrapper = pane({ save })

    await wrapper.get('select').setValue('film')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ itemType: 'film' })
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false)
  })

  it('names the fields a type change would lose, and goes on only when told to', async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError('Changing the type loses edition', 409, { data: { fields: ['edition'] } }),
      )
      .mockResolvedValueOnce(BOOK)
    const wrapper = pane({ save })

    await wrapper.get('select').setValue('film')
    await flushPromises()

    const confirm = wrapper.get('[role="alertdialog"]')
    expect(confirm.text()).toContain('The following fields will be lost:')
    expect(confirm.text()).toContain('Edition')

    await confirm.findAll('button').find((button) => button.text() === 'Change')!.trigger('click')
    await flushPromises()

    expect(save).toHaveBeenLastCalledWith({ itemType: 'film', discard: ['edition'] })
  })

  it('puts the type back when the change is not wanted', async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError('Changing the type loses edition', 409, { data: { fields: ['edition'] } }),
      )
    const wrapper = pane({ save })

    await wrapper.get('select').setValue('film')
    await flushPromises()
    await wrapper
      .get('[role="alertdialog"]')
      .findAll('button')
      .find((button) => button.text() === 'Cancel')!
      .trigger('click')

    expect(save).toHaveBeenCalledTimes(1)
    expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('book')
  })
})
