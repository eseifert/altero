import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { resetLabels } from '@/items/labels'
import { EditConflict } from '@/stores/library'
import type { CreatorEntry, ItemChanges, ItemEnvelope } from '@/stores/library'

import CreatorEditor from './CreatorEditor.vue'

const ADA: CreatorEntry = { creatorType: 'author', firstName: 'Ada', lastName: 'Lovelace' }
const CHARLES: CreatorEntry = { creatorType: 'editor', firstName: 'Charles', lastName: 'Babbage' }
const ROYAL: CreatorEntry = { creatorType: 'author', name: 'Royal Society' }

beforeEach(() => {
  setActivePinia(createPinia())
  resetLabels()
})

function editor(
  creators: CreatorEntry[],
  options: { editable?: boolean; save?: (changes: ItemChanges) => Promise<unknown> } = {},
) {
  /* Rendered inside a list, as the Info pane renders it. */
  return mount(
    {
      components: { CreatorEditor },
      props: ['creators', 'editable', 'save'],
      template:
        '<dl><CreatorEditor item-key="AAAA2345" :creators="creators" :roles="[\'author\', \'editor\', \'contributor\']" :editable="editable" :save="save" /></dl>',
    },
    {
      props: { creators, editable: options.editable ?? true, save: options.save ?? vi.fn().mockResolvedValue(null) },
      attachTo: document.body,
    },
  )
}

type Wrapper = ReturnType<typeof editor>

function names(wrapper: Wrapper, row = 0) {
  return wrapper.findAll('dd.creator')[row].findAll('input')
}

async function menu(wrapper: Wrapper, row: number, label: string): Promise<void> {
  await wrapper.findAll('[aria-haspopup="menu"]')[row].trigger('click')
  await wrapper
    .findAll('[role="menuitem"]')
    .find((item) => item.text() === label)!
    .trigger('click')
  await flushPromises()
}

describe('CreatorEditor', () => {
  it('shows each creator as the desktop does where nothing can be changed', () => {
    const wrapper = editor([ADA, ROYAL], { editable: false })

    expect(wrapper.findAll('dt').map((dt) => dt.text())).toEqual(['Author', 'Author'])
    expect(wrapper.findAll('dd').map((dd) => dd.text())).toEqual(['Lovelace, Ada', 'Royal Society'])
    expect(wrapper.find('input').exists()).toBe(false)
  })

  it('saves the whole list when a creator is left', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA, CHARLES], { save })

    const [last] = names(wrapper)
    await last.setValue('King')
    await last.trigger('blur')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({
      creators: [{ ...ADA, lastName: 'King' }, CHARLES],
    })
  })

  it('does not save between the last name and the first', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA], { save })

    const [last, first] = names(wrapper)
    await last.setValue('King')
    await last.trigger('blur', { relatedTarget: first.element })
    await flushPromises()

    expect(save).not.toHaveBeenCalled()
  })

  it('puts a creator back on Escape and saves nothing', async () => {
    const save = vi.fn()
    const wrapper = editor([ADA], { save })

    const [last] = names(wrapper)
    await last.setValue('Typo')
    await last.trigger('keydown', { key: 'Escape' })
    await flushPromises()

    expect(save).not.toHaveBeenCalled()
    expect((names(wrapper)[0].element as HTMLInputElement).value).toBe('Lovelace')
  })

  it('removes a creator and saves the rest', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA, CHARLES], { save })

    await wrapper.findAll('button[aria-label="Remove Creator"]')[0].trigger('click')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ creators: [CHARLES] })
  })

  it('removes a creator whose names are emptied, as the desktop does', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA, CHARLES], { save })

    const [last, first] = names(wrapper)
    await last.setValue('')
    await first.setValue('')
    await first.trigger('blur')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ creators: [CHARLES] })
  })

  it('removes an institution whose name is emptied, too', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ROYAL, ADA], { save })

    const [name] = names(wrapper)
    await name.setValue('')
    await name.trigger('blur')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ creators: [ADA] })
  })

  it('adds a creator after the row, in its role, and writes it once it has a name', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([CHARLES, ADA], { save })

    await wrapper.findAll('button[aria-label="Add Creator"]')[0].trigger('click')
    await flushPromises()

    const added = wrapper.findAll('dt select')[1].element as HTMLSelectElement
    expect(added.value).toBe('editor')
    expect(document.activeElement).toBe(names(wrapper, 1)[0].element)

    // Left empty, it is nothing to write.
    await names(wrapper, 1)[0].trigger('blur')
    await flushPromises()
    expect(save).not.toHaveBeenCalled()

    await names(wrapper, 1)[0].setValue('Menabrea')
    await names(wrapper, 1)[0].trigger('blur')
    await flushPromises()
    expect(save).toHaveBeenCalledWith({
      creators: [CHARLES, { creatorType: 'editor', firstName: '', lastName: 'Menabrea' }, ADA],
    })
  })

  it('offers an item with no creators a row to fill, in the primary role', () => {
    const wrapper = editor([])

    expect((wrapper.get('dt select').element as HTMLSelectElement).value).toBe('author')
    expect(names(wrapper)).toHaveLength(2)
  })

  it('changes a role at once', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA], { save })

    await wrapper.get('dt select').setValue('contributor')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ creators: [{ ...ADA, creatorType: 'contributor' }] })
  })

  it('joins first and last into one field, first name first', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA], { save })

    await menu(wrapper, 0, 'Switch to Single Field')

    expect(save).toHaveBeenCalledWith({ creators: [{ creatorType: 'author', name: 'Ada Lovelace' }] })
  })

  it('splits one field into two at the last word', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([{ creatorType: 'author', name: 'Augusta Ada King' }], { save })

    await menu(wrapper, 0, 'Switch to Two Fields')

    expect(save).toHaveBeenCalledWith({
      creators: [{ creatorType: 'author', firstName: 'Augusta Ada', lastName: 'King' }],
    })
  })

  it('moves a creator down from its options', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA, CHARLES], { save })

    await menu(wrapper, 0, 'Move Down')

    expect(save).toHaveBeenCalledWith({ creators: [CHARLES, ADA] })
  })

  it('moves a creator up from its options', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor([ADA, CHARLES], { save })

    await menu(wrapper, 1, 'Move Up')

    expect(save).toHaveBeenCalledWith({ creators: [CHARLES, ADA] })
  })

  it('offers no move off either end', async () => {
    const wrapper = editor([ADA, CHARLES])

    await wrapper.findAll('[aria-haspopup="menu"]')[0].trigger('click')

    const up = wrapper.findAll('[role="menuitem"]').find((item) => item.text() === 'Move Up')!
    expect(up.attributes('disabled')).toBeDefined()
  })

  it('says why a save was refused, and goes back to what is stored', async () => {
    const save = vi.fn().mockRejectedValue(new Error('The item has changed since you read it'))
    const wrapper = editor([ADA], { save })

    const [last] = names(wrapper)
    await last.setValue('King')
    await last.trigger('blur')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('The item has changed since you read it')
    expect((names(wrapper)[0].element as HTMLInputElement).value).toBe('Lovelace')
  })

  it('shows both lists when somebody else changed the creators, and writes the chosen one', async () => {
    const stored: ItemEnvelope = { key: 'AAAA2345', version: 5, data: { itemType: 'book', creators: [CHARLES] }, meta: {} }
    const save = vi
      .fn()
      .mockRejectedValueOnce(new EditConflict(stored, { creators: [{ ...ADA, lastName: 'King' }] }))
      .mockResolvedValue(null)
    const wrapper = editor([ADA], { save })

    const [last] = names(wrapper)
    await last.setValue('King')
    await last.trigger('blur')
    await wrapper.setProps({ creators: [CHARLES] })
    await flushPromises()

    const notice = wrapper.get('.conflict')
    expect(notice.text()).toContain('Local version: King, Ada')
    expect(notice.text()).toContain('Remote version: Babbage, Charles')
    expect((names(wrapper)[0].element as HTMLInputElement).value).toBe('Babbage')

    await notice.findAll('.conflict__choose')[0].trigger('click')
    await flushPromises()

    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith({ creators: [{ ...ADA, lastName: 'King' }] })
  })
})
