import { TextSelection } from '@tiptap/pm/state'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NoteEditor from './NoteEditor.vue'

const imageUrl = (key: string) => `/web/libraries/1/items/${key}/file`

function editor(html: string, editable = true) {
  return mount(NoteEditor, { props: { html, editable, imageUrl }, attachTo: document.body })
}

type Wrapper = ReturnType<typeof editor>

/** Selects the whole text of the note, as a reader dragging over it would. */
function selectAll(wrapper: Wrapper): void {
  const { view } = (wrapper.vm as any).$.setupState.editor
  view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 1, view.state.doc.content.size - 1)))
}

function lastChange(wrapper: Wrapper): string | undefined {
  return wrapper.emitted('change')?.at(-1)?.[0] as string | undefined
}

async function choose(wrapper: Wrapper, menu: string, entry: string): Promise<void> {
  await wrapper.find(`[aria-label="${menu}"]`).trigger('click')
  const item = wrapper.findAll('[role^="menuitem"]').find(item => item.text() === entry)
  await item!.trigger('click')
}

describe('the note editor', () => {
  it('draws the note and says nothing changed', async () => {
    const wrapper = editor('<p>Hello <strong>world</strong></p>')
    await flushPromises()
    expect(wrapper.find('.ProseMirror').html()).toContain('<strong>world</strong>')
    expect(wrapper.emitted('change')).toBeUndefined()
  })

  it('is one tab stop, moved through with the arrow keys', async () => {
    const wrapper = editor('<p>x</p>')
    const stops = () => wrapper.findAll('[role="toolbar"] button[tabindex="0"]')
    expect(stops()).toHaveLength(1)
    const first = stops()[0]!
    ;(first.element as HTMLElement).focus()
    await first.trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Redo')
    expect(stops()).toHaveLength(1)
    await wrapper.find('[aria-label="Redo"]').trigger('keydown', { key: 'End' })
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Clear Formatting')
  })

  it('makes text bold, says so, and hands back the note', async () => {
    const wrapper = editor('<p>Hello</p>')
    selectAll(wrapper)
    await wrapper.find('[aria-label="Bold"]').trigger('click')
    expect(wrapper.find('[aria-label="Bold"]').attributes('aria-pressed')).toBe('true')
    expect(lastChange(wrapper)).toBe('<div data-schema-version="9"><p><strong>Hello</strong></p>\n</div>')
  })

  it('turns a paragraph into a heading from the Format menu, and back', async () => {
    const wrapper = editor('<p>Title</p>')
    await choose(wrapper, 'Format Text', 'Heading 1')
    expect(lastChange(wrapper)).toContain('<h1>Title</h1>')
    await wrapper.find('[aria-label="Format Text"]').trigger('click')
    const checked = wrapper.findAll('[role="menuitemradio"][aria-checked="true"]').map(item => item.text())
    expect(checked).toEqual(['Heading 1'])
    await wrapper.findAll('[role="menuitemradio"]').find(item => item.text() === 'Heading 1')!.trigger('click')
    expect(lastChange(wrapper)).toContain('<p>Title</p>')
  })

  it('colours text with the desktop colours', async () => {
    const wrapper = editor('<p>Red</p>')
    selectAll(wrapper)
    await choose(wrapper, 'Text Color', 'Red')
    expect(lastChange(wrapper)).toContain('<span style="color: rgb(255, 32, 32);">Red</span>')
  })

  it('links the selection to an address, taking one without a scheme for a web page', async () => {
    const wrapper = editor('<p>Zotero</p>')
    selectAll(wrapper)
    await wrapper.find('[aria-label="Insert Link"]').trigger('click')
    await wrapper.find('#note-link').setValue('zotero.org')
    await wrapper.find('form').trigger('submit')
    expect(lastChange(wrapper)).toContain('<a href="https://zotero.org" rel="noopener noreferrer nofollow">Zotero</a>')
  })

  it('offers to open a link only to an address that is safe to follow', async () => {
    const wrapper = editor('<p><a href="javascript:alert(1)">bad</a> <a href="https://example.org">good</a></p>')
    const { view } = (wrapper.vm as any).$.setupState.editor
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 2)))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.note-editor__link-address').text()).toBe('javascript:alert(1)')
    expect(wrapper.findAll('.note-editor__link-button').map(button => button.text())).not.toContain('Open Link')
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 7)))
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.note-editor__link-button').map(button => button.text())).toContain('Open Link')
  })

  it('has no toolbar for a reader who may not change the note', async () => {
    const wrapper = editor('<p>x</p>', false)
    await flushPromises()
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false)
    expect(wrapper.find('.ProseMirror').attributes('contenteditable')).toBe('false')
  })

  it('says why a note from a newer Zotero cannot be changed', () => {
    const wrapper = editor('<div data-schema-version="11"><p>x</p></div>')
    expect(wrapper.find('[role="status"]').text()).toContain('newer version of Zotero')
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false)
  })
})
