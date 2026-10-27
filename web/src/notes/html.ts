/**
 * A note's HTML in and out of a document.
 *
 * Ported from zotero/note-editor at `acec74d`: `preprocessHTML` and
 * `schemaTransform` from `src/core/schema/transformer.js`, `toHTML` from
 * `utils.js` in the same directory, and the loading steps of `EditorCore`'s
 * constructor. The output is meant to be byte for byte what the desktop
 * writes for the same document, including its newlines between blocks and its
 * habit of returning an empty string for an empty note.
 *
 * Nothing is written on load. The note editor saves only after an edit, and
 * the rules in its schema README say so twice: a note opened and closed must
 * stay exactly as some other client wrote it.
 */
import { Fragment, DOMParser as ProseMirrorDOMParser, DOMSerializer } from '@tiptap/pm/model'
import type { Node as ProseMirrorNode, Schema } from '@tiptap/pm/model'
import { EditorState, type Transaction } from '@tiptap/pm/state'
import { fixTables } from '@tiptap/pm/tables'

import type { CitationWords } from './citations'
import { Metadata, SCHEMA_VERSION, setNoteContext } from './context'

export interface LoadedNote {
  doc: ProseMirrorNode
  metadata: Metadata
  /** Written by a newer note editor than this one: shown, never saved. */
  unsupportedSchema: boolean
}

export function preprocessHTML(html: string): {
  html: string
  metadataAttributes: Record<string, string>
} {
  const metadataAttributes: Record<string, string> = {}
  const doc = document.implementation.createHTMLDocument('')
  const container = doc.body
  container.innerHTML = html

  const metadataNode = doc.querySelector('body > div[data-schema-version]')
  if (metadataNode) {
    for (const attr of Array.from(metadataNode.attributes)) {
      // TinyMCE keeps only data attributes
      if (attr.name.startsWith('data-')) {
        metadataAttributes[attr.name] = attr.value
      }
    }
  }

  function createLink(url: string) {
    const a = doc.createElement('a')
    a.href = url
    a.appendChild(doc.createTextNode(url))
    return a
  }

  function createImage(src: string) {
    const img = doc.createElement('img')
    img.src = src
    return img
  }

  function walk(elm: Element) {
    for (let node = elm.firstChild; node; node = node.nextSibling) {
      if (node.nodeType === Node.ELEMENT_NODE) {
        const element = node as HTMLElement
        if (element.style?.backgroundImage) {
          const matched = element.style.backgroundImage.match(/url\(["']?([^"']*)["']?\)/)
          if (matched && /^(https?|data):/.test(matched[1]!)) {
            element.parentElement!.insertBefore(createImage(matched[1]!), element)
          }
        }

        if (element.nodeName !== 'IMG' && element.getAttribute('src')) {
          element.parentElement!.insertBefore(createLink(element.getAttribute('src')!), element)
        }
        walk(element)
      }
    }
  }

  walk(container)

  return { html: container.innerHTML, metadataAttributes }
}

/**
 * A note from the note editor's first schema, brought up to its second.
 *
 * `Zotero.Notes.upgradeSchemaV1` from zotero/zotero, which the desktop runs on
 * every note it opens for editing -- and saves at once. Here it is applied in
 * memory only, so a note opened and left stays as it was, and one edited is
 * saved as the desktop would save it. Item data moves from each citation into
 * the container, and an annotation keeps only the properties schema 2 knew.
 */
export function upgradeSchemaV1(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const container = doc.querySelector('body > div[data-schema-version]')
  if (!container || parseInt(container.getAttribute('data-schema-version')!) !== 1) {
    return html
  }

  let stored: { uris: string[]; itemData: unknown }[] = []
  try {
    const data = JSON.parse(decodeURIComponent(container.getAttribute('data-citation-items')!))
    if (Array.isArray(data)) stored = data
  } catch {
    // As in the original: unreadable item data is none.
  }

  const pullItemData = (citationItem: { uris: string[]; itemData?: unknown }) => {
    const { uris, itemData } = citationItem
    if (itemData) {
      delete citationItem.itemData
      if (!stored.find(item => item.uris.some(uri => uris.includes(uri)))) {
        stored.push({ uris, itemData })
      }
    }
  }

  for (const node of Array.from(doc.querySelectorAll('.citation[data-citation]'))) {
    try {
      const citation = JSON.parse(decodeURIComponent(node.getAttribute('data-citation')!))
      citation.citationItems.forEach(pullItemData)
      node.setAttribute('data-citation', encodeURIComponent(JSON.stringify(citation)))
    } catch {
      // Left as it was, as the original logs and moves on.
    }
  }

  for (const node of Array.from(doc.querySelectorAll('*[data-annotation]'))) {
    try {
      const annotation = JSON.parse(decodeURIComponent(node.getAttribute('data-annotation')!))
      if (annotation.citationItem) pullItemData(annotation.citationItem)
      const kept = {
        uri: annotation.uri,
        text: annotation.text,
        color: annotation.color,
        pageLabel: annotation.pageLabel,
        position: annotation.position,
        citationItem: annotation.citationItem,
      }
      node.setAttribute('data-annotation', encodeURIComponent(JSON.stringify(kept)))
    } catch {
      // Left as it was.
    }
  }

  if (stored.length) {
    container.setAttribute('data-citation-items', encodeURIComponent(JSON.stringify(stored)))
  }
  container.setAttribute('data-schema-version', '2')
  return doc.body.innerHTML
}

// Additional transformations that can't be described with schema alone
export function schemaTransform(state: EditorState): Transaction | null {
  const { tr } = state
  let updated = false
  state.doc.descendants((node, pos) => {
    // Do not allow to be wrapped in any mark
    if (['image'].includes(node.type.name) && node.marks.length) {
      tr.setNodeMarkup(pos, null, node.attrs, [])
      updated = true
    }
    // Force inline code to have only plain text
    else if (!node.isText && node.marks.find(mark => mark.type.name === 'code')) {
      tr.removeMark(pos, pos + 1, state.schema.marks.code)
      updated = true
    }
  })
  return updated ? tr : null
}

/**
 * Reads a note as the note editor opens one. `editable` is whether the reader
 * may change it; the item data no citation uses any more is dropped only then,
 * as the original does, and only takes effect when the note is next saved.
 */
export function parseNote(
  schema: Schema,
  html: string,
  options: { editable: boolean; words?: CitationWords },
): LoadedNote {
  const metadata = new Metadata()
  setNoteContext(schema, metadata, options.words)

  const { html: body, metadataAttributes } = preprocessHTML(
    options.editable ? upgradeSchemaV1(html) : html,
  )
  metadata.parseAttributes(metadataAttributes)
  const unsupportedSchema = metadata.schemaVersion > SCHEMA_VERSION

  let doc = ProseMirrorDOMParser.fromSchema(schema).parse(
    new DOMParser().parseFromString(body, 'text/html').body,
  )

  let state = EditorState.create({ doc })
  const tr = schemaTransform(state)
  if (tr) {
    state = state.apply(tr)
  }
  const fix = fixTables(state)
  if (fix) {
    state = state.apply(fix.setMeta('addToHistory', false))
  }
  doc = state.doc

  if (options.editable && !unsupportedSchema) {
    metadata.deleteUnusedCitationItems(doc)
  }

  return { doc, metadata, unsupportedSchema }
}

const TEXT_NODES = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre']

const BLOCK_NODES = [
  'ol',
  'ul',
  'li',
  'hr',
  'blockquote',
  'table',
  'th',
  'tr',
  'td',
  'thead',
  'tbody',
  'tfoot',
]

/**
 * The note editor's text `toDOM` writes every second space of a run as a
 * non-breaking one, which TinyMCE needed. prosemirror-model stopped asking a
 * text node's `toDOM` in 1.25.3, but Zotero builds the note editor with 1.25.2,
 * so the desktop still does it, and it is done here before serializing. An
 * atom writes its own text (`$x$` for maths) and is left alone, as it was.
 */
function withSequentialSpaces(fragment: Fragment): Fragment {
  const children: ProseMirrorNode[] = []
  fragment.forEach(node => {
    if (node.isText) {
      const text = node.text!.replace(/ {2}/g, '  ')
      children.push(text === node.text ? node : node.type.schema.text(text, node.marks))
    } else if (node.isAtom) {
      children.push(node)
    } else {
      children.push(node.copy(withSequentialSpaces(node.content)))
    }
  })
  return Fragment.fromArray(children)
}

/** The note editor's `toHTML`: what is saved as the item's `note`. */
export function serializeNote(content: Fragment, metadata: Metadata): string {
  // Return an empty string if note is empty to allow Zotero to determine if
  // note is empty. Though, this won't allow container metadata to survive
  // after note is cleared and then re-opened
  if (
    content.childCount === 1 &&
    content.firstChild!.isTextblock &&
    content.firstChild!.content.size === 0
  ) {
    return ''
  }

  const schema = content.firstChild!.type.schema
  setNoteContext(schema, metadata, (schema.cached.note as { words?: CitationWords })?.words)

  const doc = document.implementation.createHTMLDocument('New')
  const fragment = DOMSerializer.fromSchema(schema).serializeFragment(
    withSequentialSpaces(content),
    { document: doc },
  )
  const tmp = doc.body

  const container = doc.createElement('div')
  const metadataAttributes = metadata.serializeAttributes()
  for (const key of Object.keys(metadataAttributes).sort()) {
    container.setAttribute(key, metadataAttributes[key]!)
  }

  tmp.append(container)
  container.append(fragment)

  let nodes = tmp.querySelectorAll([...TEXT_NODES, ...BLOCK_NODES].join(','))
  for (const node of Array.from(nodes)) {
    if (BLOCK_NODES.includes(node.nodeName.toLowerCase())) {
      node.insertBefore(doc.createTextNode('\n'), node.firstChild)
    }
    node.parentNode!.insertBefore(doc.createTextNode('\n'), node.nextSibling)
  }

  nodes = tmp.querySelectorAll('li')
  for (const node of Array.from(nodes)) {
    if (node.children.length === 1 && node.firstElementChild!.nodeName === 'P') {
      node.firstElementChild!.replaceWith(...Array.from(node.firstElementChild!.childNodes))
    }
  }

  // Decrease schema version number if not using underline annotations, so an
  // editor that knows version 9 can still change the note. (The original's
  // like step from 9 to 8 for maths cannot apply while the version is 10.)
  if (SCHEMA_VERSION === 10 && !tmp.querySelector('span.underline')) {
    container.setAttribute('data-schema-version', '9')
  }

  let html = tmp.innerHTML.trim()
  // Normalize text by precomposing characters and accents into single composed
  // characters to prevent indexing issues
  html = html.normalize('NFC')
  return html
}
