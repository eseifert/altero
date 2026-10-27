import { Schema } from '@tiptap/pm/model'
import { describe, expect, it } from 'vitest'

import { formatCitationItem } from './citations'
import { Metadata } from './context'
import { parseNote, serializeNote } from './html'
import { marks } from './marks'
import { nodes } from './nodes'
import { noteSchema } from './schema'

function roundTrip(html: string, editable = true): string {
  const { doc, metadata } = parseNote(noteSchema(), html, { editable })
  return serializeNote(doc.content, metadata)
}

const citation = encodeURIComponent(
  JSON.stringify({
    citationItems: [{ uris: ['http://zotero.org/users/1/items/AAAAAAAA'], locator: '12' }],
    properties: {},
  }),
)
const citationItems = encodeURIComponent(
  JSON.stringify([
    {
      uris: ['http://zotero.org/users/1/items/AAAAAAAA'],
      itemData: {
        id: 1,
        type: 'book',
        title: 'A Book',
        author: [{ family: 'Doe', given: 'Jane' }],
        issued: { 'date-parts': [['2019']] },
      },
    },
  ]),
)

describe('the note schema', () => {
  it('is the original specs, in their order, whatever Tiptap makes of them', () => {
    const plain = new Schema({ nodes, marks })
    const tiptap = noteSchema()

    expect(Object.keys(tiptap.nodes)).toEqual(Object.keys(plain.nodes))
    expect(Object.keys(tiptap.marks)).toEqual(Object.keys(plain.marks))
    for (const name of Object.keys(plain.nodes)) {
      const ours = tiptap.nodes[name]!.spec
      const theirs = plain.nodes[name]!.spec
      for (const field of ['content', 'group', 'inline', 'atom', 'marks', 'tableRole'] as const) {
        expect(ours[field], `${name}.${field}`).toEqual(theirs[field])
      }
      expect(Object.keys(ours.attrs ?? {}), name).toEqual(Object.keys(theirs.attrs ?? {}))
    }
  })
})

// The expected HTML is what zotero/note-editor at `acec74d` writes for the same
// input, run with the prosemirror-model versions its lock file pins (1.25.2);
// see "P2.1" in the roadmap's decisions for how it was produced.
const WRITTEN: [string, string, string][] = [
  [
    'paragraphs and headings',
    '<h1>Title</h1><p>Some <strong>bold</strong> and <em>italic</em> text.</p>',
    '<div data-schema-version="9"><h1>Title</h1>\n<p>Some <strong>bold</strong> and <em>italic</em> text.</p>\n</div>',
  ],
  [
    'lists, the paragraph inside each item unwrapped',
    '<ul><li>one</li><li>two</li></ul><ol start="3"><li>three</li></ol>',
    '<div data-schema-version="9"><ul>\n<li>\none\n</li>\n<li>\ntwo\n</li>\n</ul>\n<ol start="3">\n<li>\nthree\n</li>\n</ol>\n</div>',
  ],
  [
    "a table, whose cell colour is read as its text's too",
    '<table><tr><th>head</th><td colspan="2" style="background-color: red">cell</td></tr></table>',
    '<div data-schema-version="9"><table>\n<tbody>\n<tr>\n<th>\n<p>head</p>\n</th>\n<td colspan="2" style="background-color: red;">\n<p><span style="background-color: red;">cell</span></p>\n</td>\n</tr>\n</tbody>\n</table>\n</div>',
  ],
  [
    'an indent, written on the side the text starts',
    '<p style="text-align: center; padding-left: 80px" dir="rtl">x</p>',
    '<div data-schema-version="9"><p style="text-align: center; padding-right: 80px;" dir="rtl" data-indent="2">x</p>\n</div>',
  ],
  [
    'marks in the schema order, a strike as a span',
    '<p><u><em><strong>x</strong></em></u><s>s</s><sub>2</sub><sup>3</sup></p>',
    '<div data-schema-version="9"><p><strong><em><u>x</u></em></strong><span style="text-decoration: line-through;">s</span><sub>2</sub><sup>3</sup></p>\n</div>',
  ],
  [
    'colours as the browser serializes them, and links',
    '<p><span style="color: #ff2020">red</span><span style="background-color: #ffd400">hi</span><a href="https://example.org">link</a><code>c</code></p>',
    '<div data-schema-version="9"><p><span style="color: rgb(255, 32, 32);">red</span><span style="background-color: rgb(255, 212, 0);">hi</span><a href="https://example.org" rel="noopener noreferrer nofollow">link</a><code>c</code></p>\n</div>',
  ],
  [
    'maths, and code whose second space is non-breaking',
    '<pre class="math">$$x^2$$</pre><p><span class="math">$y$</span></p><pre>a  b</pre>',
    '<div data-schema-version="9"><pre class="math">$$x^2$$</pre>\n<p><span class="math">$y$</span></p>\n<pre>a &nbsp;b</pre>\n</div>',
  ],
  [
    'a quote and a rule',
    '<blockquote><p>q</p></blockquote><hr><p>after</p>',
    '<div data-schema-version="9"><blockquote>\n<p>q</p>\n</blockquote>\n<hr>\n<p>after</p>\n</div>',
  ],
  [
    'an embedded image, its attributes in the schema order',
    '<p><img data-attachment-key="BBBBBBBB" width="200" height="100"></p>',
    '<div data-schema-version="9"><p><img alt="" width="200" height="100" data-attachment-key="BBBBBBBB"></p>\n</div>',
  ],
]

describe('a note written as the desktop writes it', () => {
  it.each(WRITTEN)('%s', (_, html, written) => {
    expect(roundTrip(html)).toBe(written)
  })

  it.each(WRITTEN)('%s, read back unchanged', (_, __, written) => {
    expect(roundTrip(written)).toBe(written)
  })

  it.each([
    [
      'an annotation and a citation',
      `<div data-citation-items="${citationItems}" data-schema-version="9"><p><span class="highlight" data-annotation="%7B%22attachmentURI%22%3A%22x%22%7D">quoted</span> <span class="citation" data-citation="${citation}">(<span class="citation-item">Doe, 2019, p. 12</span>)</span></p>\n</div>`,
    ],
    [
      'an underline annotation, which needs version 10',
      '<div data-schema-version="10"><p><span class="underline" data-annotation="%7B%22attachmentURI%22%3A%22x%22%7D">under</span></p>\n</div>',
    ],
  ])('keeps %s', (_, html) => {
    expect(roundTrip(html)).toBe(html)
  })
})

describe('what the note editor changes on writing', () => {
  it('stamps its own schema version, 9 without an underline annotation', () => {
    expect(roundTrip('<p>old</p>')).toBe('<div data-schema-version="9"><p>old</p>\n</div>')
  })

  it('reads an attribute only the way the note editor reads it', () => {
    // Tiptap would otherwise take each attribute of the same name as it stands
    expect(roundTrip('<p align="right" dir="auto" data-indent="x">x</p>')).toBe(
      '<div data-schema-version="9"><p>x</p>\n</div>',
    )
  })

  it('turns TinyMCE padding into an indent', () => {
    expect(roundTrip('<p style="padding-left: 40px;">x</p>')).toBe(
      '<div data-schema-version="9"><p style="padding-left: 40px;" data-indent="1">x</p>\n</div>',
    )
  })

  it("ignores a <b> Google Docs set in normal weight", () => {
    expect(roundTrip('<p><b style="font-weight: normal">x</b></p>')).toBe(
      '<div data-schema-version="9"><p>x</p>\n</div>',
    )
  })

  it('keeps sequential spaces with a non-breaking one, but not in maths', () => {
    // Typed, since reading HTML collapses a run of spaces outside a <pre>
    const schema = noteSchema()
    const typed = schema.node('doc', null, [
      schema.node('paragraph', null, [schema.text('a  b', [schema.marks.strong!.create()])]),
    ])
    expect(serializeNote(typed.content, new Metadata())).toContain('<strong>a &nbsp;b</strong>')
    expect(roundTrip('<p>a&nbsp;&nbsp;b</p>')).toContain('a&nbsp;&nbsp;b')
    expect(roundTrip('<p><span class="math">$a  b$</span></p>')).toContain('$a  b$')
  })

  it('formats a citation again from the item data', () => {
    const html = `<div data-citation-items="${citationItems}" data-schema-version="9"><p><span class="citation" data-citation="${citation}">(stale)</span></p></div>`
    expect(roundTrip(html)).toContain('(<span class="citation-item">Doe, 2019, p. 12</span>)')
  })

  it('drops item data nothing refers to, but only when editing', () => {
    const html = `<div data-citation-items="${citationItems}" data-schema-version="9"><p>none</p>\n</div>`
    expect(roundTrip(html)).toBe('<div data-schema-version="9"><p>none</p>\n</div>')
    expect(roundTrip(html, false)).toBe(html)
  })

  it('moves an annotation from `uri` to `attachmentURI`', () => {
    const annotation = encodeURIComponent(JSON.stringify({ uri: 'x', text: 'old' }))
    expect(roundTrip(`<p><span class="highlight" data-annotation="${annotation}">q</span></p>`)).toContain(
      'data-annotation="%7B%22attachmentURI%22%3A%22x%22%7D"',
    )
  })

  it('writes an empty note as nothing at all', () => {
    expect(roundTrip('<div data-schema-version="9"><p></p></div>')).toBe('')
    expect(roundTrip('')).toBe('')
  })

  it('composes accents', () => {
    expect(roundTrip('<p>é</p>')).toContain('<p>é</p>')
  })

  it('keeps a source attribute as a link', () => {
    expect(roundTrip('<p><video src="https://example.org/v"></video></p>')).toContain(
      '<a href="https://example.org/v" rel="noopener noreferrer nofollow">https://example.org/v</a>',
    )
  })
})

describe('a note from a newer note editor', () => {
  it('says so, so that it is shown and never saved', () => {
    const { unsupportedSchema } = parseNote(
      noteSchema(),
      '<div data-schema-version="11"><p>x</p></div>',
      { editable: true },
    )
    expect(unsupportedSchema).toBe(true)
  })

  it('keeps its item data even when asked to edit', () => {
    const { metadata } = parseNote(
      noteSchema(),
      `<div data-citation-items="${citationItems}" data-schema-version="11"><p>x</p></div>`,
      { editable: true },
    )
    expect(metadata.citationItems).toHaveLength(1)
  })
})

describe("a citation's text", () => {
  const item = (author: { family?: string; literal?: string }[], extra = {}) => ({
    uris: ['u'],
    itemData: { author, issued: { 'date-parts': [[2020]] }, title: 'T' },
    ...extra,
  })

  it.each([
    [item([{ family: 'Doe' }]), 'Doe, 2020'],
    [item([{ family: 'Doe' }, { literal: 'ACME' }]), 'Doe and ACME, 2020'],
    [item([{ family: 'A' }, { family: 'B' }, { family: 'C' }]), 'A et al., 2020'],
    [item([]), '“T”, 2020'],
    [item([{ family: 'Doe' }], { locator: '3-5' }), 'Doe, 2020, pp. 3-5'],
    [item([{ family: 'Doe' }], { locator: '3', label: 'chap.' }), 'Doe, 2020, chap. 3'],
    [item([{ family: 'Doe' }], { prefix: 'see', suffix: 'passim' }), 'see Doe, 2020 passim'],
    [item([{ family: 'Doe' }], { prefix: '(', suffix: ')' }), '(Doe, 2020)'],
  ])('%#', (citationItem, text) => {
    expect(formatCitationItem(citationItem)).toBe(text)
  })

  it('takes the words of the language saving it', () => {
    expect(
      formatCitationItem(item([{ family: 'A' }, { family: 'B' }]), { and: 'und', etAl: 'u. a.' }),
    ).toBe('A und B, 2020')
  })
})
