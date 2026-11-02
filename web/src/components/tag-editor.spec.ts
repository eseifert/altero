import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { colorIndex, compareTags, containsEmoji } from '@/items/tags'
import { useLibraryStore } from '@/stores/library'
import type { ItemChanges, ItemEnvelope, SaveOptions } from '@/stores/library'

import TagEditor from './TagEditor.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

function article(tags: { tag: string; type?: number }[]): ItemEnvelope {
  return { key: 'AAAA2345', version: 3, data: { itemType: 'book', title: 'Whales', tags }, meta: {} }
}

type Save = (changes: ItemChanges) => Promise<unknown>

function editor(item: ItemEnvelope, options: { editable?: boolean; save?: Save } = {}) {
  return mount(TagEditor, {
    props: { item, editable: options.editable ?? true, save: options.save ?? vi.fn().mockResolvedValue(null) },
    attachTo: document.body,
  })
}

type Wrapper = ReturnType<typeof editor>

/** A save that answers the way the store does: the pane is handed the new item. */
function answering(wrapper: () => Wrapper) {
  return vi.fn(async (changes: ItemChanges) => {
    const item = wrapper().props('item') as ItemEnvelope
    await wrapper().setProps({ item: { ...item, version: item.version + 1, data: { ...item.data, tags: changes.tags } } })
  })
}

function names(wrapper: Wrapper): string[] {
  return wrapper.findAll('.tag-pill__name').map((chip) => chip.text())
}

async function addTag(wrapper: Wrapper): Promise<void> {
  await wrapper.find('[aria-label="Add Tag"]').trigger('click')
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLibraryStore().libraryId = 1
  requestMock.mockReset()
  requestMock.mockResolvedValue({ tags: [], colors: [] })
})

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('tag order', () => {
  it('puts coloured tags first by position, then emoji, then the rest alphabetically', () => {
    const colors = colorIndex([
      { name: 'urgent', color: '#FF6666' },
      { name: 'appendix', color: '#5FB236' },
    ])
    const order = ['zebra', 'appendix', 'Banana', '⭐ starred', 'urgent', 'apple'].sort((a, b) =>
      compareTags(a, b, colors, 'en-US'),
    )

    expect(order).toEqual(['urgent', 'appendix', '⭐ starred', 'apple', 'Banana', 'zebra'])
  })

  it('counts a pictograph as an emoji and a copyright sign as not', () => {
    expect(containsEmoji('read 📚')).toBe(true)
    expect(containsEmoji('© 2020')).toBe(false)
  })
})

describe('TagEditor', () => {
  it('shows the tags in the desktop’s order, coloured ones with their colour', () => {
    useLibraryStore().tagColors = [{ name: 'toread', color: '#FF6666' }]
    const wrapper = editor(article([{ tag: 'whales' }, { tag: 'toread' }, { tag: 'auto', type: 1 }]), {
      editable: false,
    })

    expect(names(wrapper)).toEqual(['toread', 'auto, Automatically added tag', 'whales'])
    expect(wrapper.find('.tags__tag--colored').attributes('style')).toContain('--tag-color: #FF6666')
    expect(wrapper.find('.tags__tag--automatic').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Add Tag"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Remove Tag"]').exists()).toBe(false)
    expect(wrapper.find('.tag-pill__edit').exists()).toBe(false)
  })

  it('is not drawn for an item with no tags that cannot be changed', () => {
    expect(editor(article([]), { editable: false }).find('section').exists()).toBe(false)
  })

  it('adds a tag on Enter and stays open for the next', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'whales', type: 1 }]), { save })

    await addTag(wrapper)
    const box = wrapper.find('input')
    await box.setValue(' squid ')
    await box.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ tags: [{ tag: 'whales', type: 1 }, { tag: 'squid' }] }, expect.anything())
    expect(wrapper.find('input').exists()).toBe(true)
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('')
  })

  it('adds what was typed when the box is left, and closes it', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([]), { save })

    await addTag(wrapper)
    await wrapper.find('input').setValue('squid')
    await wrapper.find('input').trigger('blur')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ tags: [{ tag: 'squid' }] }, expect.anything())
    expect(wrapper.find('input').exists()).toBe(false)
  })

  it('writes a second tag on top of the first, never beside it', async () => {
    let wrapper!: Wrapper
    const answer = answering(() => wrapper)
    /* The first save is still on its way when the second tag is typed. */
    let release: () => void = () => {}
    const held = new Promise<void>((resolve) => (release = resolve))
    const save = vi.fn(async (changes: ItemChanges) => {
      if (save.mock.calls.length === 1) await held
      await answer(changes)
    })
    wrapper = editor(article([]), { save })

    await addTag(wrapper)
    const box = wrapper.find('input')
    await box.setValue('squid')
    await box.trigger('keydown', { key: 'Enter' })
    await box.setValue('krill')
    await box.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(save).toHaveBeenCalledTimes(1)
    release()
    await flushPromises()

    expect(save.mock.calls.map(([changes]) => changes.tags)).toEqual([
      [{ tag: 'squid' }],
      [{ tag: 'squid' }, { tag: 'krill' }],
    ])
  })

  it('keeps the name passive, with editing on the pencil', async () => {
    const library = useLibraryStore()
    const filter = vi.spyOn(library, 'toggleTag').mockResolvedValue()
    const save = vi.fn()
    const wrapper = editor(article([{ tag: 'whales' }]), { save })
    expect(wrapper.get('.tag-pill__name').element.tagName).toBe('SPAN')
    await wrapper.get('.tag-pill__name').trigger('click')
    expect(filter).not.toHaveBeenCalled()
    expect(wrapper.find('input, dialog').exists()).toBe(false)
    expect(save).not.toHaveBeenCalled()
  })

  it('renames inline through the pencil, on this item only', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'whale', type: 1 }, { tag: 'squid' }]), { save })

    await wrapper.get('[aria-label="Rename “whale”"]').trigger('click')
    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(wrapper.find('.tag-pill__hint').exists()).toBe(false)
    expect(wrapper.get('input').element).toBe(document.activeElement)
    await wrapper.get('input').setValue('whales')
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ tags: [{ tag: 'whales' }, { tag: 'squid' }] }, expect.anything())
  })

  it('refuses an empty rename without removing the tag', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'squid' }, { tag: 'whale' }]), { save })

    await wrapper.get('[aria-label="Rename “squid”"]').trigger('click')
    await wrapper.get('input').setValue('   ')
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(save).not.toHaveBeenCalled()
    expect(wrapper.get('.tag-pill__error').text()).toBe('A tag needs a name.')
  })

  it('puts a name back on Escape', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'squid' }]), { save })

    await wrapper.get('[aria-label="Rename “squid”"]').trigger('click')
    await wrapper.find('input').setValue('octopus')
    await wrapper.get('input').trigger('keydown', { key: 'Escape' })
    await flushPromises()

    expect(save).not.toHaveBeenCalled()
    expect(names(wrapper)).toEqual(['squid'])
  })

  it('leaves the draft behind when another item carries the same tag', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'squid' }]), { save })
    await wrapper.get('.tag-pill__edit').trigger('click')
    await wrapper.get('input').setValue('octopus')

    await wrapper.setProps({ item: { ...article([{ tag: 'squid' }]), key: 'BBBB2345' } })

    expect(wrapper.find('input').exists()).toBe(false)
    expect(names(wrapper)).toEqual(['squid'])
    expect(save).not.toHaveBeenCalled()
  })

  it('keeps a refused rename and its draft in the inline field', async () => {
    const save = vi.fn().mockRejectedValue(new Error('Rename refused'))
    const wrapper = editor(article([{ tag: 'squid' }]), { save })
    await wrapper.get('[aria-label="Rename “squid”"]').trigger('click')
    await wrapper.get('input').setValue('octopus')
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.get('.tag-pill__error').text()).toBe('Rename refused')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('octopus')
    expect(wrapper.find('.tags__error').exists()).toBe(false)
  })

  it('removes a tag with its cross', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'squid' }, { tag: 'whale' }]), { save })

    await wrapper.findAll('[aria-label="Remove Tag"]')[1].trigger('click')
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ tags: [{ tag: 'squid' }] }, expect.anything())
  })

  it('reads several lines pasted as several tags', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'squid' }]), { save })

    await addTag(wrapper)
    const event = new Event('paste', { cancelable: true }) as ClipboardEvent
    Object.defineProperty(event, 'clipboardData', { value: { getData: () => 'krill\nsquid\r\n plankton \n' } })
    wrapper.find('input').element.dispatchEvent(event)
    await flushPromises()

    expect(event.defaultPrevented).toBe(true)
    expect(save).toHaveBeenCalledWith({ tags: [{ tag: 'squid' }, { tag: 'krill' }, { tag: 'plankton' }] }, expect.anything())
  })

  it('offers the library’s tags the item lacks, those starting with the text first', async () => {
    vi.useFakeTimers()
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'whales' }]), { save })
    requestMock.mockResolvedValue({
      tags: [{ tag: 'blue whales' }, { tag: 'whales' }, { tag: 'whale song' }].map((tag) => ({ ...tag, type: 0, numItems: 1 })),
    })

    await addTag(wrapper)
    await wrapper.find('input').setValue('wha')
    await wrapper.find('input').trigger('input')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()

    expect(requestMock).toHaveBeenCalledWith('/web/libraries/1/tags?q=wha&limit=50')
    const options = wrapper.findAll('[role="option"]')
    expect(options.map((option) => option.text())).toEqual(['whale song', 'blue whales'])

    await wrapper.find('input').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.find('input').attributes('aria-activedescendant')).toBe(options[0].attributes('id'))
    await wrapper.find('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(save).toHaveBeenCalledWith({ tags: [{ tag: 'whales' }, { tag: 'whale song' }] }, expect.anything())
  })

  it('adds the tag again to the tags somebody else saved meanwhile', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = editor(article([{ tag: 'whales' }]), { save })

    await addTag(wrapper)
    await wrapper.find('input').setValue('squid')
    await wrapper.find('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    const { rebase } = save.mock.calls[0][1] as SaveOptions
    expect(rebase!(article([{ tag: 'whales' }, { tag: 'krill' }]))).toEqual({
      tags: [{ tag: 'whales' }, { tag: 'krill' }, { tag: 'squid' }],
    })
    // Added there as well: nothing left to write.
    expect(rebase!(article([{ tag: 'squid' }, { tag: 'whales' }]))).toBeNull()
  })

  it('shows the server’s refusal', async () => {
    const save = vi.fn().mockRejectedValue(new Error('Tag is too long'))
    const wrapper = editor(article([{ tag: 'squid' }]), { save })

    await wrapper.find('[aria-label="Remove Tag"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toBe('Tag is too long')
  })
})
