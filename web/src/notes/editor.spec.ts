import { TextSelection } from '@tiptap/pm/state'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createNoteEditor, type NoteEditor, safeHref } from './editor'

const imageUrl = (key: string) => `/web/libraries/1/items/${key}/file`
let open: NoteEditor | undefined

function make(html: string, extra: Partial<Parameters<typeof createNoteEditor>[0]> = {}) {
  const element = document.createElement('div')
  document.body.append(element)
  open = createNoteEditor({ html, editable: true, imageUrl, ...extra })
  open.editor.mount(element)
  return open
}

afterEach(() => {
  open?.editor.destroy()
  open = undefined
  document.body.innerHTML = ''
})

function typeAtEnd(note: NoteEditor, text: string) {
  const { view } = note.editor
  const end = view.state.doc.content.size - 1
  view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, end)).insertText(text))
}

describe('the note editor', () => {
  it('writes nothing when a note is opened', () => {
    const onChange = vi.fn()
    make('<div data-schema-version="8"><p style="padding-left: 40px">old <b>note</b></p></div>', { onChange })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('hands back the note as the desktop would save it after an edit', () => {
    const onChange = vi.fn()
    make('<p>Hello</p>', { onChange })
    typeAtEnd(make('<p>Hello</p>', { onChange }), ' world')
    expect(onChange).toHaveBeenLastCalledWith('<div data-schema-version="9"><p>Hello world</p>\n</div>')
  })

  it('refuses edits to a note from a newer note editor', () => {
    const note = make('<div data-schema-version="11"><p>x</p></div>')
    expect(note.unsupportedSchema).toBe(true)
    expect(note.editor.isEditable).toBe(false)
  })

  it('is read-only when asked', () => {
    expect(make('<p>x</p>', { editable: false }).editor.isEditable).toBe(false)
  })

  it('draws a citation with its text', () => {
    const items = encodeURIComponent(
      JSON.stringify([{ uris: ['u'], itemData: { author: [{ family: 'Doe' }], issued: { 'date-parts': [[2019]] } } }]),
    )
    const citation = encodeURIComponent(JSON.stringify({ citationItems: [{ uris: ['u'] }], properties: {} }))
    const note = make(
      `<div data-citation-items="${items}" data-schema-version="9"><p><span class="citation" data-citation="${citation}">(x)</span></p></div>`,
    )
    expect(note.editor.view.dom.querySelector('.citation')?.textContent).toBe('(Doe, 2019)')
  })

  it("prefixes a heading's id on the page, never in the note", () => {
    const note = make('<h1 id="app">Title</h1>')
    expect(note.editor.view.dom.querySelector('h1')?.id).toBe('user-content-app')
    expect(note.html()).toContain('<h1 id="app">Title</h1>')
  })

  it('draws an embedded image from its attachment and fetches no other', () => {
    const note = make(
      '<p><img data-attachment-key="ABCD2345"><img src="https://example.org/track.png"><img src="data:image/png;base64,AAAA"></p>',
    )
    const images = Array.from(note.editor.view.dom.querySelectorAll('img.note-image'))
    expect(images.map(img => img.getAttribute('src'))).toEqual([
      '/web/libraries/1/items/ABCD2345/file',
      null,
      'data:image/png;base64,AAAA',
    ])
    expect(note.html()).toContain('src="https://example.org/track.png"')
  })

  it('never follows a link itself', () => {
    const note = make('<p><a href="javascript:alert(1)">x</a></p>', { editable: false })
    const link = note.editor.view.dom.querySelector('a')!
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    link.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })
})

describe('a link address', () => {
  it.each([
    ['https://example.org/a', 'https://example.org/a'],
    ['mailto:a@example.org', 'mailto:a@example.org'],
    ['javascript:alert(1)', null],
    ['data:text/html,x', null],
    [' JAVASCRIPT:alert(1)', null],
  ])('%s', (href, safe) => {
    expect(safeHref(href)).toBe(safe)
  })
})
