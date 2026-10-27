/**
 * What a note carries besides its content, and where the schema finds it.
 *
 * Ported from zotero/note-editor `src/core/schema/metadata.js` and the citation
 * half of `utils.js` at `acec74d`. A note's outermost element is a
 * `<div data-schema-version="…">` whose `data-citation-items` holds the item
 * data its citations and annotations refer to by URI, so that each citation
 * need not repeat it. The citation's `toDOM` needs that data to write its text,
 * and ProseMirror hands a `toDOM` nothing but the node, so — as in the original
 * — it is left on `schema.cached`, which every schema has one of. Tiptap builds
 * a schema per editor, so two editors on a page do not share it.
 */
import type { DOMOutputSpec, Node as ProseMirrorNode, Schema } from '@tiptap/pm/model'

import {
  type CitationItem,
  type CitationWords,
  ENGLISH_CITATION_WORDS,
  formatCitationItem,
} from './citations'

/**
 * The note editor's `schema.version`, written into every note it saves.
 * A note claiming a higher one was written by a newer editor and opens
 * read-only, so as not to drop what this one does not know.
 */
export const SCHEMA_VERSION = 10

export class Metadata {
  // Keeps schema version number from metadata container, but when serializing
  // uses the current one from `SCHEMA_VERSION`
  schemaVersion = 0
  citationItems: CitationItem[] = []

  serializeAttributes(): Record<string, string> {
    const attributes: Record<string, string> = {}
    attributes['data-schema-version'] = SCHEMA_VERSION.toString()
    if (this.citationItems.length) {
      attributes['data-citation-items'] = encodeURIComponent(JSON.stringify(this.citationItems))
    }
    return attributes
  }

  parseAttributes(attributes: Record<string, string>): void {
    const schemaVersion = attributes['data-schema-version']
    if (schemaVersion) {
      const version = parseInt(schemaVersion)
      if (Number.isInteger(version)) {
        this.schemaVersion = version
      }
    }

    try {
      const encoded = attributes['data-citation-items']
      if (encoded) {
        const citationItems = JSON.parse(decodeURIComponent(encoded))
        if (Array.isArray(citationItems)) {
          this.citationItems = citationItems
        }
      }
    } catch {
      // As in the original: an unreadable container keeps no items.
    }
  }

  fillCitationItemsWithData(citationItems: CitationItem[]): void {
    for (const citationItem of citationItems) {
      const item = this.citationItems.find(item =>
        item.uris.some(uri => citationItem.uris.includes(uri)),
      )
      if (item) {
        citationItem.itemData = item.itemData
      }
    }
  }

  /**
   * Drops the item data no citation or annotation refers to any more. The
   * note editor does this when a note is opened for editing, which changes
   * nothing until the note is next saved for some other reason.
   */
  deleteUnusedCitationItems(doc: ProseMirrorNode): boolean {
    const used = new Set<CitationItem>()
    doc.descendants(node => {
      let citationItems: CitationItem[] | undefined
      if (node.attrs.citation) {
        citationItems = node.attrs.citation.citationItems
      } else if (node.attrs.annotation && node.attrs.annotation.citationItem) {
        citationItems = [node.attrs.annotation.citationItem]
      }
      if (Array.isArray(citationItems)) {
        for (const citationItem of citationItems) {
          const uris: string[] = Array.isArray(citationItem?.uris) ? citationItem.uris : []
          const item = this.citationItems.find(item => item.uris.some(uri => uris.includes(uri)))
          if (item) {
            used.add(item)
          }
        }
      }
    })

    const before = this.citationItems.length
    this.citationItems = this.citationItems.filter(item => used.has(item))
    return this.citationItems.length !== before
  }
}

interface NoteContext {
  metadata: Metadata
  words: CitationWords
}

export function setNoteContext(schema: Schema, metadata: Metadata, words?: CitationWords): void {
  schema.cached.note = { metadata, words: words ?? ENGLISH_CITATION_WORDS } satisfies NoteContext
}

function noteContext(schema: Schema): NoteContext {
  return (schema.cached.note as NoteContext | undefined) ?? {
    metadata: new Metadata(),
    words: ENGLISH_CITATION_WORDS,
  }
}

/** A citation's text, `(Doe, 2019; Roe and Poe, 2020)`, as the original writes it. */
export function serializeCitationInnerHTML(node: ProseMirrorNode): (string | DOMOutputSpec)[] {
  const { metadata, words } = noteContext(node.type.schema)
  const children: (string | DOMOutputSpec)[] = ['(']
  try {
    const citation = JSON.parse(JSON.stringify(node.attrs.citation))
    metadata.fillCitationItemsWithData(citation.citationItems)
    citation.citationItems.forEach((citationItem: CitationItem, index: number, array: unknown[]) => {
      if (citationItem.itemData) {
        children.push(['span', { class: 'citation-item' }, formatCitationItem(citationItem, words)])
        if (index !== array.length - 1) {
          children.push('; ')
        }
      }
    })
  } catch {
    // As in the original, a malformed citation is written as its parentheses.
  }
  children.push(')')
  return children
}
