import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { EXPORT_FORMAT_STORAGE_KEY } from '@/exportformats'

import ExportDialog from './ExportDialog.vue'

/**
 * The two questions this dialog asks: which items, and in which format.
 *
 * What is checked is which formats are offered, that the rows picked out are
 * the answer offered first, that the link the reader presses is the one for
 * what they chose, and that the format is remembered — the client keeps
 * `export.lastTranslator` because nobody picks a format twice.
 */

const LIBRARY = { id: 'library', label: 'My Library' }
const SELECTION = { id: 'selection', label: '3 items selected' }

function open(scopes: { id: string; label: string }[] = [LIBRARY]) {
  return mount(ExportDialog, {
    props: {
      scopes,
      link: (format: string, scope: string) => `/export?format=${format}&scope=${scope}`,
    },
  })
}

function download(wrapper: ReturnType<typeof open>) {
  return wrapper.get('.dialog__download')
}

describe('the export dialog', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('offers the four formats the server can write', () => {
    const wrapper = open()

    const offered = wrapper.findAll('option').map((option) => option.text())

    expect(offered).toEqual(['BibLaTeX', 'BibTeX', 'CSL JSON', 'RIS'])
  })

  it('starts on BibTeX, and on whatever was chosen last after that', async () => {
    expect(download(open()).attributes('href')).toContain('format=bibtex')

    const wrapper = open()
    await wrapper.get('select').setValue('ris')
    await download(wrapper).trigger('click')

    expect(localStorage.getItem(EXPORT_FORMAT_STORAGE_KEY)).toBe('ris')
    expect(download(open()).attributes('href')).toContain('format=ris')
  })

  it('fetches the file for the format chosen', async () => {
    const wrapper = open()

    await wrapper.get('select').setValue('csljson')

    /* A link, not a button: this is what makes the browser stream the file to
       disk and take its name from the response. */
    expect(download(wrapper).attributes('href')).toBe('/export?format=csljson&scope=library')
    expect(download(wrapper).attributes('download')).toBeDefined()
  })

  it('names what it is about when there is nothing to choose', () => {
    const wrapper = open([{ id: 'selection', label: 'Whales' }])

    expect(wrapper.get('.dialog__what').text()).toBe('Whales')
    expect(wrapper.findAll('input[type="radio"]')).toHaveLength(0)
  })

  it('asks which items when there is more than one answer', () => {
    const wrapper = open([SELECTION, LIBRARY])

    const offered = wrapper.findAll('.dialog__check').map((entry) => entry.text())

    expect(offered).toEqual(['3 items selected', 'My Library'])
    expect(wrapper.find('legend').text()).toBe('What to export')
  })

  it('offers the rows picked out first, and exports those unless told otherwise', () => {
    /* A selection is a decision somebody has just made; an export that ignored
       it would be answering a question nobody asked. */
    const wrapper = open([SELECTION, LIBRARY])

    expect(download(wrapper).attributes('href')).toContain('scope=selection')
  })

  it('follows the wider answer once it is given', async () => {
    const wrapper = open([SELECTION, LIBRARY])

    await wrapper.findAll('input[type="radio"]')[1].setValue(true)

    expect(download(wrapper).attributes('href')).toContain('scope=library')
  })

  it('closes once the download has been started', async () => {
    const wrapper = open()

    await download(wrapper).trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('closes without exporting anything on Cancel', async () => {
    const wrapper = open()

    await wrapper.findAll('button').at(-1)?.trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
