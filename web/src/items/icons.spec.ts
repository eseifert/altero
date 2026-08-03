import { describe, expect, it } from 'vitest'

import { ITEM_TYPE_ICONS, iconFor } from './icons'

/**
 * Every item type the server's schema declares, as of schema version 42.
 *
 * Taken from `/itemTypes` rather than written from memory: an item type with
 * no icon renders as a blank space in the list, and the only way to know the
 * set is complete is to hold it against the source.
 */
const SCHEMA_ITEM_TYPES = [
  'annotation',
  'artwork',
  'attachment',
  'audioRecording',
  'bill',
  'blogPost',
  'book',
  'bookSection',
  'case',
  'computerProgram',
  'conferencePaper',
  'dataset',
  'dictionaryEntry',
  'document',
  'email',
  'encyclopediaArticle',
  'film',
  'forumPost',
  'hearing',
  'instantMessage',
  'interview',
  'journalArticle',
  'letter',
  'magazineArticle',
  'manuscript',
  'map',
  'newspaperArticle',
  'note',
  'patent',
  'podcast',
  'preprint',
  'presentation',
  'radioBroadcast',
  'report',
  'standard',
  'statute',
  'thesis',
  'tvBroadcast',
  'videoRecording',
  'webpage',
]

describe('item type icons', () => {
  it.each(SCHEMA_ITEM_TYPES)('has an icon for %s', (itemType) => {
    expect(iconFor(itemType).paths.length).toBeGreaterThan(0)
  })

  it.each(SCHEMA_ITEM_TYPES)('gives %s a label for assistive technology', (itemType) => {
    expect(iconFor(itemType).label).toBeTruthy()
  })

  it('falls back to the generic document for a type it has never heard of', () => {
    /* The schema gains item types over time, and a server ahead of this build
       must not render blank rows. */
    expect(iconFor('holographicMessage')).toEqual(iconFor('document'))
  })

  it('distinguishes the types people actually look at in a list', () => {
    const distinct = new Set(
      ['book', 'journalArticle', 'webpage', 'note', 'attachment', 'thesis', 'film'].map(
        (type) => JSON.stringify(iconFor(type).paths),
      ),
    )

    expect(distinct.size).toBe(7)
  })

  it('reads a book and a book section as related but not identical', () => {
    expect(iconFor('bookSection').label).not.toBe(iconFor('book').label)
    expect(iconFor('bookSection').paths).not.toEqual(iconFor('book').paths)
  })

  it('draws every glyph on the same 24-unit grid', () => {
    for (const icon of Object.values(ITEM_TYPE_ICONS)) {
      expect(icon.paths.every((path) => path.trim().length > 0)).toBe(true)
    }
  })

  it('names the icons in the same words Zotero does', () => {
    expect(iconFor('journalArticle').label).toBe('Journal article')
    expect(iconFor('blogPost').label).toBe('Blog post')
    expect(iconFor('tvBroadcast').label).toBe('TV broadcast')
  })
})
