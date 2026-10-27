import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { loadLabels, resetLabels } from '@/items/labels'
import type { ItemChanges, ItemEnvelope } from '@/stores/library'

import InfoPane from './InfoPane.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const SCHEMA = {
  itemTypes: { attachment: 'Attachment' },
  fields: { itemType: 'Item Type', title: 'Title', accessDate: 'Accessed', url: 'URL' },
  creatorTypes: {},
  mappings: {},
  types: { attachment: { fields: ['title', 'accessDate', 'url'], creatorTypes: [] } },
}

function attachment(linkMode: string, filename = 'Smith 2024.pdf'): ItemEnvelope {
  return {
    key: 'FILE2345',
    version: 3,
    data: { itemType: 'attachment', linkMode, title: 'PDF', filename, contentType: 'application/pdf' },
    meta: {},
  }
}

beforeEach(async () => {
  setActivePinia(createPinia())
  requestMock.mockReset()
  resetLabels()
  requestMock.mockResolvedValue(SCHEMA)
  await loadLabels()
})

function pane(item: ItemEnvelope, save = vi.fn().mockResolvedValue(item)) {
  const wrapper = mount(InfoPane, { props: { item, editable: true, save }, attachTo: document.body })
  return { wrapper, save }
}

async function renameTo(wrapper: ReturnType<typeof pane>['wrapper'], name: string): Promise<void> {
  await wrapper.get('[aria-labelledby="info-FILE2345-filename"]').trigger('click')
  const box = wrapper.get('textarea')
  await box.setValue(name)
  await box.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

describe('the file’s name', () => {
  it('is a field after the title, for a file stored here', () => {
    const { wrapper } = pane(attachment('imported_file'))

    expect(wrapper.findAll('dt').map((dt) => dt.text())).toEqual(['Item Type', 'Title', 'Filename'])
  })

  it('is edited with the title, as the attachment box edits them, and the rest is shown', () => {
    const item = attachment('imported_url')
    item.data.url = 'https://example.org/page'
    item.data.accessDate = '2026-10-27 10:00:00'
    const { wrapper } = pane(item)

    expect(wrapper.findAll('dt').map((dt) => dt.text())).toEqual([
      'Item Type',
      'Title',
      'Filename',
      'URL',
      'Accessed',
    ])
    const editable = wrapper.findAll('.info__value').map((button) => button.attributes('aria-labelledby'))
    expect(editable).toEqual(['info-FILE2345-title', 'info-FILE2345-filename'])
    // An attachment's type is not changed, and it has no creators.
    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Add Creator')
  })

  it('is no field for a link', () => {
    const { wrapper } = pane(attachment('linked_url', ''))

    expect(wrapper.findAll('dt').map((dt) => dt.text())).not.toContain('Filename')
  })

  it('is renamed in place', async () => {
    const { wrapper, save } = pane(attachment('imported_file'))

    await renameTo(wrapper, '  Smith and Jones 2024.pdf ')

    expect(save).toHaveBeenCalledWith({ fields: { filename: 'Smith and Jones 2024.pdf' } } satisfies ItemChanges)
  })

  it('keeps its extension when none is typed', async () => {
    const { wrapper, save } = pane(attachment('imported_file'))

    await renameTo(wrapper, 'Smith and Jones')

    expect(save).toHaveBeenCalledWith({ fields: { filename: 'Smith and Jones.pdf' } })
  })

  it('writes nothing for the same name, or for none', async () => {
    const { wrapper, save } = pane(attachment('imported_file'))

    await renameTo(wrapper, 'Smith 2024.pdf')
    await renameTo(wrapper, '   ')

    expect(save).not.toHaveBeenCalled()
  })

  it('asks before changing the extension, and keeps the old one if told to', async () => {
    const { wrapper, save } = pane(attachment('imported_file'))

    await renameTo(wrapper, 'notes.txt')

    expect(save).not.toHaveBeenCalled()
    const ask = wrapper.get('[role="alertdialog"]')
    expect(ask.text()).toContain('from “.pdf” to “.txt”')
    await ask.findAll('button').find((button) => button.text() === 'Keep .pdf')!.trigger('click')
    expect(save).toHaveBeenCalledWith({ fields: { filename: 'notes.pdf' } })
  })

  it('uses the new extension if told to', async () => {
    const { wrapper, save } = pane(attachment('imported_file'))

    await renameTo(wrapper, 'notes.txt')
    await wrapper.findAll('button').find((button) => button.text() === 'Use .txt')!.trigger('click')

    expect(save).toHaveBeenCalledWith({ fields: { filename: 'notes.txt' } })
  })
})
