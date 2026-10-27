import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { carriesFiles, droppedFiles, dropTarget } from '@/filedrop'
import type { ItemEnvelope } from '@/stores/library'
import { useUploadStore } from '@/stores/uploads'

import ItemDetail from './ItemDetail.vue'
import UploadProgress from './UploadProgress.vue'
import WebLinkDialog from './WebLinkDialog.vue'

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: vi.fn().mockResolvedValue({ items: [] }),
}))

function entry(key: string, data: Partial<ItemEnvelope['data']> = {}): ItemEnvelope {
  return { key, version: 1, data: { itemType: 'book', title: key, ...data }, meta: {} }
}

const BOOK = entry('BOOK2345')
const STORED = entry('FILE2345', { itemType: 'attachment', linkMode: 'imported_file', filename: 'a.pdf' })
const LINK = entry('LINK2345', { itemType: 'attachment', linkMode: 'linked_url', url: 'https://example.org' })

function detail(item: ItemEnvelope, props: Record<string, unknown> = {}) {
  return mount(ItemDetail, {
    props: {
      item,
      children: [],
      libraryId: 1,
      fileUrl: (key: string) => `/files/${key}`,
      writable: true,
      filesEditable: true,
      ...props,
    },
    attachTo: document.body,
  })
}

async function menu(wrapper: ReturnType<typeof detail>): Promise<string[]> {
  await wrapper.get('[aria-label="Add Attachment"]').trigger('click')
  return wrapper.findAll('[role="menuitem"]').map((item) => item.text())
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  document.body.innerHTML = ''
})

describe('the Attachments section', () => {
  it('offers to attach a file or a web link to a regular item', async () => {
    const wrapper = detail(BOOK)

    expect(await menu(wrapper)).toEqual(['Attach File…', 'Attach Web Link…'])
  })

  it('offers only the link where the group keeps files to itself', async () => {
    const wrapper = detail(BOOK, { filesEditable: false })

    expect(await menu(wrapper)).toEqual(['Attach Web Link…'])
  })

  it('says which was chosen', async () => {
    const wrapper = detail(BOOK)
    await menu(wrapper)

    await wrapper.findAll('[role="menuitem"]')[0]!.trigger('click')
    expect(wrapper.emitted('attachFile')).toHaveLength(1)

    await menu(wrapper)
    await wrapper.findAll('[role="menuitem"]')[1]!.trigger('click')
    expect(wrapper.emitted('attachLink')).toHaveLength(1)
  })

  it('offers nothing to a reader, or in the trash', () => {
    expect(detail(BOOK, { writable: false }).find('[aria-label="Add Attachment"]').exists()).toBe(false)
    expect(detail(entry('GONE2345', { deleted: true })).find('[aria-label="Add Attachment"]').exists()).toBe(false)
  })

  it('takes files dropped on the pane of a regular item', () => {
    expect(detail(BOOK).get('article').attributes('data-file-drop')).toBe('item:BOOK2345')
    expect(detail(STORED).get('article').attributes('data-file-drop')).toBeUndefined()
  })
})

describe('replacing a file', () => {
  function replaceButton(wrapper: ReturnType<typeof detail>) {
    return wrapper.findAll('button').find((button) => button.text() === 'Replace File…')
  }

  it('is offered on an attachment whose file is stored here', async () => {
    const wrapper = detail(STORED)

    await replaceButton(wrapper)!.trigger('click')

    expect(wrapper.emitted('replaceFile')).toHaveLength(1)
  })

  it('is not offered on a link, to a reader, or where files are kept to admins', () => {
    expect(replaceButton(detail(LINK))).toBeUndefined()
    expect(replaceButton(detail(STORED, { writable: false }))).toBeUndefined()
    expect(replaceButton(detail(STORED, { filesEditable: false }))).toBeUndefined()
  })
})

describe('the uploads panel', () => {
  it('shows each file going up with a bar, and cancels one', async () => {
    const store = useUploadStore()
    let cancelled = false
    void store.track('paper.pdf', 2048, (progress, signal) => {
      progress(1024)
      signal.addEventListener('abort', () => (cancelled = true))
      return new Promise(() => {})
    })
    const wrapper = mount(UploadProgress)
    await flushPromises()

    const bar = wrapper.get('progress')
    expect(bar.attributes('aria-label')).toBe('Uploading paper.pdf')
    expect(bar.attributes('value')).toBe('1024')
    expect(bar.attributes('max')).toBe('2048')

    await wrapper.get('[aria-label="Cancel upload of paper.pdf"]').trigger('click')
    expect(cancelled).toBe(true)
  })

  it('keeps a failure, as an alert, until it is dismissed', async () => {
    const store = useUploadStore()
    store.refuse('huge.pdf', 'Larger than the 1 GB this server accepts')
    const wrapper = mount(UploadProgress)
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('Larger than the 1 GB this server accepts')
    expect(wrapper.find('progress').exists()).toBe(false)

    await wrapper.get('[aria-label="Dismiss"]').trigger('click')
    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('draws nothing when nothing is going up', () => {
    expect(mount(UploadProgress).find('section').exists()).toBe(false)
  })
})

describe('the web link dialog', () => {
  async function submit(address: string, title = '') {
    const wrapper = mount(WebLinkDialog, { attachTo: document.body })
    const [link, name] = wrapper.findAll('input')
    await link!.setValue(address)
    await name!.setValue(title)
    await wrapper.get('form').trigger('submit')
    return wrapper
  }

  it('sends the address cleaned and the title trimmed', async () => {
    const wrapper = await submit('example.org/paper', '  A paper ')

    expect(wrapper.emitted('submit')).toEqual([[{ url: 'http://example.org/paper', title: 'A paper' }]])
  })

  it.each([
    ['words', 'This is not an address. Check it and try again.'],
    ['file:///home/ada/a.pdf', 'A file on your computer cannot be linked from the browser.'],
    ['javascript:alert(1)', 'This kind of address cannot be attached.'],
  ])('refuses %s, saying why', async (address, message) => {
    const wrapper = await submit(address)

    expect(wrapper.emitted('submit')).toBeUndefined()
    expect(wrapper.get('[role="alert"]').text()).toBe(message)
    expect(wrapper.get('#web-link-address').attributes('aria-invalid')).toBe('true')
  })
})

describe('files from the computer', () => {
  function transfer(entries: { file: File; directory?: boolean }[]): DataTransfer {
    return {
      types: ['Files'],
      files: entries.map((entry) => entry.file),
      items: entries.map((entry) => ({
        kind: 'file',
        getAsFile: () => entry.file,
        webkitGetAsEntry: () => ({ isDirectory: Boolean(entry.directory) }),
      })),
    } as unknown as DataTransfer
  }

  it('tells a drag of files from any other', () => {
    expect(carriesFiles({ dataTransfer: { types: ['Files'] } } as unknown as DragEvent)).toBe(true)
    expect(carriesFiles({ dataTransfer: { types: ['text/plain'] } } as unknown as DragEvent)).toBe(false)
  })

  it('finds the nearest target, a file target first', () => {
    document.body.innerHTML = `
      <section data-file-drop="list:"><div data-drop="collection:C"><span id="a"></span></div>
      <div data-file-drop="item:K" data-drop="x"><span id="b"></span></div><span id="c"></span></section>`

    expect(dropTarget(document.getElementById('a'))).toBe('collection:C')
    expect(dropTarget(document.getElementById('b'))).toBe('item:K')
    expect(dropTarget(document.getElementById('c'))).toBe('list:')
    expect(dropTarget(document.body)).toBeNull()
  })

  it('leaves folders out and counts them', () => {
    const paper = new File(['x'], 'paper.pdf')
    const folder = new File([], 'Papers')

    expect(droppedFiles(transfer([{ file: paper }, { file: folder, directory: true }]))).toEqual({
      files: [paper],
      folders: 1,
    })
  })
})
