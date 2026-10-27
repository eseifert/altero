import { TextSelection } from '@tiptap/pm/state'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import NoteEditor from './NoteEditor.vue'

const imageUrl = (key: string) => `/web/libraries/1/items/${key}/file`

// jsdom lays nothing out, and the "/" list is placed at the slash, which
// ProseMirror measures with a range's rectangles: give it empty ones.
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList
  Range.prototype.getBoundingClientRect = () => new DOMRect()
}

/** A finger's device, where the tools sit on the keyboard; a mouse otherwise. */
function pointer(coarse: boolean): void {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    query =>
      ({
        matches: coarse && query.includes('coarse'),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  )
}

afterEach(() => vi.restoreAllMocks())

async function editor(html: string, { editable = true, coarse = true } = {}) {
  pointer(coarse)
  const wrapper = mount(NoteEditor, { props: { html, editable, imageUrl }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof editor>>

function view(wrapper: Wrapper) {
  return (wrapper.vm as any).$.setupState.editor.view
}

/** Selects the whole text of the note, as a reader dragging over it would. */
function selectAll(wrapper: Wrapper): void {
  const v = view(wrapper)
  v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, 1, v.state.doc.content.size - 1)))
}

/** Types at the cursor, through the editor's own input handling. */
function type(wrapper: Wrapper, text: string): void {
  const v = view(wrapper)
  for (const ch of text) {
    const { from, to } = v.state.selection
    const handled = v.someProp('handleTextInput', (f: any) => f(v, from, to, ch, () => v.state.tr.insertText(ch, from, to)))
    if (!handled) v.dispatch(v.state.tr.insertText(ch, from, to))
  }
}

/** A key pressed in the text, through the editor's own key handling. */
function press(wrapper: Wrapper, key: string): void {
  const v = view(wrapper)
  v.someProp('handleKeyDown', (f: any) => f(v, new KeyboardEvent('keydown', { key })))
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
    const wrapper = await editor('<p>Hello <strong>world</strong></p>')
    expect(wrapper.find('.ProseMirror').html()).toContain('<strong>world</strong>')
    expect(wrapper.emitted('change')).toBeUndefined()
  })

  it('has no toolbar for a reader who may not change the note', async () => {
    const wrapper = await editor('<p>x</p>', { editable: false })
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false)
    expect(wrapper.find('.ProseMirror').attributes('contenteditable')).toBe('false')
  })

  it('says why a note from a newer Zotero cannot be changed', async () => {
    const wrapper = await editor('<div data-schema-version="11"><p>x</p></div>')
    expect(wrapper.find('[role="status"]').text()).toContain('newer version of Zotero')
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false)
  })
})

describe('with a mouse', () => {
  it('stands nothing over the text until it is wanted', async () => {
    const wrapper = await editor('<p>x</p>', { coarse: false })
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false)
  })

  it('offers the block types on "/", narrowed by what follows, and applies one', async () => {
    const wrapper = await editor('<p>Title</p><p></p>', { coarse: false })
    const v = view(wrapper)
    v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, v.state.doc.content.size - 1)))
    type(wrapper, '/he')
    await flushPromises()
    const options = wrapper.findAll('[role="option"]').map(option => option.text())
    expect(options).toEqual(['Heading 1', 'Heading 2', 'Heading 3'])
    // The cursor stays in the text, which points at the entry Enter would choose.
    expect(v.dom.getAttribute('aria-activedescendant')).toBe(wrapper.find('[role="option"]').attributes('id'))

    press(wrapper, 'ArrowDown')
    press(wrapper, 'Enter')
    await flushPromises()
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(lastChange(wrapper)).toBe('<div data-schema-version="9"><p>Title</p>\n<h2></h2>\n</div>')
  })

  it('finds an entry by its Markdown shorthand too', async () => {
    const wrapper = await editor('<p></p>', { coarse: false })
    type(wrapper, '/ul')
    await flushPromises()
    // First, as the one it starts; Divider follows for "rule", which holds it.
    expect(wrapper.findAll('[role="option"]').map(option => option.text())).toEqual(['Bulleted List', 'Divider'])
  })

  it('closes on Escape, leaves the slash, and stays closed for it', async () => {
    const wrapper = await editor('<p></p>', { coarse: false })
    type(wrapper, '/h')
    await flushPromises()
    press(wrapper, 'Escape')
    await flushPromises()
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    type(wrapper, 'e')
    await flushPromises()
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(wrapper.find('.ProseMirror').text()).toBe('/he')
  })

  it('does not open on a slash inside a word', async () => {
    const wrapper = await editor('<p></p>', { coarse: false })
    // "he" would offer the headings, were a slash in a word a trigger
    type(wrapper, 'and/he')
    await flushPromises()
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  })
})

describe('on a finger\'s device', () => {
  it('is one tab stop, moved through with the arrow keys', async () => {
    const wrapper = await editor('<p>x</p>')
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
    const wrapper = await editor('<p>Hello</p>')
    selectAll(wrapper)
    await wrapper.find('[aria-label="Bold"]').trigger('click')
    expect(wrapper.find('[aria-label="Bold"]').attributes('aria-pressed')).toBe('true')
    expect(lastChange(wrapper)).toBe('<div data-schema-version="9"><p><strong>Hello</strong></p>\n</div>')
  })

  it('turns a paragraph into a heading from the Format menu, and back', async () => {
    const wrapper = await editor('<p>Title</p>')
    await choose(wrapper, 'Format Text', 'Heading 1')
    expect(lastChange(wrapper)).toContain('<h1>Title</h1>')
    await wrapper.find('[aria-label="Format Text"]').trigger('click')
    const checked = wrapper.findAll('[role="menuitemradio"][aria-checked="true"]').map(item => item.text())
    expect(checked).toEqual(['Heading 1'])
    await wrapper.findAll('[role="menuitemradio"]').find(item => item.text() === 'Heading 1')!.trigger('click')
    expect(lastChange(wrapper)).toContain('<p>Title</p>')
  })

  it('colours text with the desktop colours', async () => {
    const wrapper = await editor('<p>Red</p>')
    selectAll(wrapper)
    await choose(wrapper, 'Text Color', 'Red')
    expect(lastChange(wrapper)).toContain('<span style="color: rgb(255, 32, 32);">Red</span>')
  })

  it('links the selection to an address, taking one without a scheme for a web page', async () => {
    const wrapper = await editor('<p>Zotero</p>')
    selectAll(wrapper)
    await wrapper.find('[aria-label="Insert Link"]').trigger('click')
    await wrapper.find('input[type="url"]').setValue('zotero.org')
    await wrapper.find('form').trigger('submit')
    expect(lastChange(wrapper)).toContain('<a href="https://zotero.org" rel="noopener noreferrer nofollow">Zotero</a>')
  })

  it('offers to open a link only to an address that is safe to follow', async () => {
    const wrapper = await editor('<p><a href="javascript:alert(1)">bad</a> <a href="https://example.org">good</a></p>')
    const v = view(wrapper)
    v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, 2)))
    await flushPromises()
    expect(wrapper.find('.note-editor__link-address').text()).toBe('javascript:alert(1)')
    expect(wrapper.findAll('.note-editor__link-button').map(button => button.text())).not.toContain('Open Link')
    v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, 7)))
    await flushPromises()
    expect(wrapper.findAll('.note-editor__link-button').map(button => button.text())).toContain('Open Link')
  })
})
