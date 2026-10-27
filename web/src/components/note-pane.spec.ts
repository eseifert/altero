import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { EditConflict, type ItemChanges, type ItemEnvelope } from '@/stores/library'

import NoteEditor from './NoteEditor.vue'
import NotePane from './NotePane.vue'

function note(html: string, version = 3): ItemEnvelope {
  return { key: 'NOTE2345', version, data: { itemType: 'note', note: html }, meta: {} }
}

function pane(item: ItemEnvelope, save: (changes: ItemChanges) => Promise<unknown>) {
  return mount(NotePane, {
    props: { item, editable: true, save, imageUrl: (key: string) => `/file/${key}` },
    attachTo: document.body,
  })
}

type Wrapper = ReturnType<typeof pane>

/** What the reader typing would hand the pane. */
function typed(wrapper: Wrapper, html: string): void {
  wrapper.findComponent(NoteEditor).vm.$emit('change', html)
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('a note in the item pane', () => {
  it('saves a second after the last change, once', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = pane(note('<p>a</p>'), save)
    typed(wrapper, '<p>ab</p>')
    await vi.advanceTimersByTimeAsync(600)
    typed(wrapper, '<p>abc</p>')
    await vi.advanceTimersByTimeAsync(600)
    expect(save).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(400)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith({ note: '<p>abc</p>' })
    await flushPromises()
    expect(wrapper.find('.note-pane__state').text()).toBe('Saved.')
  })

  it('saves what is waiting when it is closed', async () => {
    const save = vi.fn().mockResolvedValue(null)
    const wrapper = pane(note('<p>a</p>'), save)
    typed(wrapper, '<p>left</p>')
    wrapper.unmount()
    await flushPromises()
    expect(save).toHaveBeenCalledWith({ note: '<p>left</p>' })
  })

  it('sends what was typed during a save after it, not alongside it', async () => {
    let finish: () => void = () => {}
    const save = vi.fn(() => new Promise<void>(resolve => (finish = resolve)))
    const wrapper = pane(note('<p>a</p>'), save)
    typed(wrapper, '<p>one</p>')
    await vi.advanceTimersByTimeAsync(1000)
    typed(wrapper, '<p>two</p>')
    await vi.advanceTimersByTimeAsync(1000)
    expect(save).toHaveBeenCalledTimes(1)

    finish()
    await flushPromises()
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith({ note: '<p>two</p>' })
  })

  it('says a note was not saved, and saves it again when asked', async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(null)
    const wrapper = pane(note('<p>a</p>'), save)
    typed(wrapper, '<p>b</p>')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Not saved.')

    await wrapper.find('.note-pane__retry').trigger('click')
    await flushPromises()
    expect(save).toHaveBeenLastCalledWith({ note: '<p>b</p>' })
    expect(wrapper.find('.note-pane__state').text()).toBe('Saved.')
  })

  it('offers both versions by title when the note changed elsewhere, and keeps the one chosen', async () => {
    const fresh = note('<p>Theirs</p>', 4)
    const save = vi.fn().mockRejectedValueOnce(new EditConflict(fresh, { note: '<p>Mine</p>' })).mockResolvedValue(null)
    const wrapper = pane(note('<p>a</p>'), save)
    typed(wrapper, '<p>Mine</p>')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.text()).toContain('Local version: Mine')
    expect(wrapper.text()).toContain('Remote version: Theirs')

    await wrapper.findAll('.conflict__choose')[0]!.trigger('click')
    await flushPromises()
    expect(save).toHaveBeenLastCalledWith({ note: '<p>Mine</p>' })
    expect(wrapper.text()).not.toContain('Remote version')
  })

  it('takes the other version without writing anything', async () => {
    const fresh = note('<p>Theirs</p>', 4)
    const save = vi.fn().mockRejectedValueOnce(new EditConflict(fresh, { note: '<p>Mine</p>' }))
    const wrapper = pane(note('<p>a</p>'), save)
    typed(wrapper, '<p>Mine</p>')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await wrapper.setProps({ item: fresh })

    await wrapper.findAll('.conflict__choose')[1]!.trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(2000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.ProseMirror').text()).toBe('Theirs')
  })

  it('draws a note changed elsewhere again while nothing typed here is waiting', async () => {
    const wrapper = pane(note('<p>Before</p>'), vi.fn().mockResolvedValue(null))
    await flushPromises()
    await wrapper.setProps({ item: note('<p>After</p>', 4) })
    await flushPromises()
    expect(wrapper.find('.ProseMirror').text()).toBe('After')
  })

  it('leaves the text being typed alone when the note changes elsewhere', async () => {
    const wrapper = pane(note('<p>Before</p>'), vi.fn().mockResolvedValue(null))
    await flushPromises()
    typed(wrapper, '<p>Typing</p>')
    await wrapper.setProps({ item: note('<p>After</p>', 4) })
    await flushPromises()
    expect(wrapper.find('.ProseMirror').text()).toBe('Before')
  })
})
