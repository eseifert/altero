import { TextSelection } from '@tiptap/pm/state'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createNoteEditor, type NoteEditor } from './editor'
import { undoCommand } from './behaviour'

let note: NoteEditor | undefined
afterEach(() => {
  note?.editor.destroy()
  document.body.innerHTML = ''
})

function open(html: string) {
  const onChange = vi.fn()
  note = createNoteEditor({ html, editable: true, imageUrl: key => key, onChange })
  note.editor.mount(document.body.appendChild(document.createElement('div')))
  return { ...note, dom: note.editor.view.dom, onChange }
}

describe('note direction is a view preference', () => {
  it('lets each paragraph, heading and list choose its direction without rewriting the note', () => {
    const current = open('<h2>שלום</h2><p>English</p><ul><li>اردو</li></ul>')
    expect(current.dom.getAttribute('dir')).toBe('auto')
    for (const element of current.dom.querySelectorAll('h2, p, ul')) {
      expect(element.getAttribute('dir'), element.outerHTML).toBe('auto')
    }
    expect(current.html()).not.toContain('dir=')
    expect(current.onChange).not.toHaveBeenCalled()
  })

  it('honors explicit directions on blocks and their ancestors', () => {
    const current = open('<p dir="rtl">English</p><ul dir="rtl"><li>English</li></ul><p>العربية</p>')
    expect(current.dom.querySelector('p')?.getAttribute('dir')).toBe('rtl')
    expect(current.dom.querySelector('ul')?.getAttribute('dir')).toBe('rtl')
    expect(current.dom.querySelector('ul p')?.getAttribute('dir')).toBeNull()
    expect(current.dom.lastElementChild?.getAttribute('dir')).toBe('auto')
    expect(current.html().match(/dir="rtl"/g)).toHaveLength(2)
    expect(current.html()).not.toContain('dir="auto"')
  })

  it('updates direction after edits and undo without storing automatic direction', () => {
    const current = open('<p>English</p>')
    const { view } = current.editor
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 1)).insertText('فارسی '))
    expect(current.dom.querySelector('p')?.getAttribute('dir')).toBe('auto')
    expect(current.onChange).toHaveBeenLastCalledWith('<div data-schema-version="9"><p>فارسی English</p>\n</div>')
    undoCommand(view.state, view.dispatch)
    expect(current.dom.querySelector('p')?.getAttribute('dir')).toBe('auto')
    expect(current.html()).toBe('<div data-schema-version="9"><p>English</p>\n</div>')
  })
})
