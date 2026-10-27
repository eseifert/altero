import { describe, expect, it } from 'vitest'

import browserNotes from './corpus/browser-notes.json'
import corpus from './corpus/zotero-10.0.6.json'
import { parseNote, serializeNote, upgradeSchemaV1 } from './html'
import { noteSchema } from './schema'

/*
 * Notes as Zotero Desktop's own note editor wrote them.
 *
 * `corpus/zotero-10.0.6.json` is recorded by the `note-corpus` desktop
 * acceptance scenario: each note was given to a real Zotero 10.0.6 as a client
 * sent it (`sent`), held by the desktop (`stored` -- the same, but for a
 * schema-1 note, which the desktop upgrades on showing it), then opened in its
 * item pane and saved, unedited, by the shipped note editor (`written`). The
 * editor here must write what that one wrote: in Firefox, with the
 * prosemirror-model it is built with, the styles serialized by Firefox's CSSOM.
 */

function save(html: string): string {
  const { doc, metadata } = parseNote(noteSchema(), html, { editable: true })
  return serializeNote(doc.content, metadata)
}

const cases = corpus.cases.map(entry => [entry.name, entry] as const)

describe(`notes written by Zotero ${corpus.desktop}'s note editor`, () => {
  it('cover what the scenario stores', () => {
    expect(corpus.cases.length).toBeGreaterThanOrEqual(29)
    expect(corpus.cases.filter(entry => entry.stored !== entry.written).length).toBeGreaterThan(20)
  })

  it.each(cases)('%s: saved here as the desktop saved it', (_, entry) => {
    expect(save(entry.stored)).toBe(entry.written)
  })

  it.each(cases)('%s: a desktop note saved here is unchanged', (_, entry) => {
    expect(save(entry.written)).toBe(entry.written)
  })

  it.each(cases.filter(([, entry]) => entry.sent !== entry.stored))(
    '%s: upgraded here as the desktop upgrades it',
    (_, entry) => {
      expect(upgradeSchemaV1(entry.sent)).toBe(entry.stored)
      expect(save(entry.sent)).toBe(entry.written)
    },
  )

  it('upgrades only a schema-1 note', () => {
    const html = '<div data-schema-version="2"><p>x</p></div>'
    expect(upgradeSchemaV1(html)).toBe(html)
    expect(upgradeSchemaV1('<p>x</p>')).toBe('<p>x</p>')
  })
})

describe('the notes the desktop acceptance writes through the browser', () => {
  it.each(Object.entries(browserNotes))('%s is what the editor here saves', (_, html) => {
    expect(save(html)).toBe(html)
  })
})
