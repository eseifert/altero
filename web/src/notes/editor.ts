/**
 * A Tiptap editor over one note.
 *
 * The editor draws a note's own markup on the page, not the cleaned copy
 * `sanitize.ts` makes for display, so what the schema lets through is held to
 * the same rules here, in the view only: the saved HTML stays exactly what was
 * written. A heading's `id` is prefixed as the cleaner prefixes it, so a note
 * cannot name an element this page looks up; an image is drawn only from its
 * embedded attachment or a `data:` URL, never fetched from elsewhere; and a
 * link is never followed by the browser, but opened by `openLink` when its
 * address is one a reader can safely be sent to.
 */
import type { AnyExtension } from '@tiptap/core'
import { DOMSerializer, type Node as ProseMirrorNode } from '@tiptap/pm/model'
import type { NodeView } from '@tiptap/pm/view'
import { Dropcursor, Gapcursor, Placeholder } from '@tiptap/extensions'
import { Editor, type Node } from '@tiptap/vue-3'

import { NoteBehaviour } from './behaviour'
import type { CitationWords } from './citations'
import { type Metadata, setNoteContext } from './context'
import { parseNote, serializeNote } from './html'
import { noteSchema, noteSchemaExtensions } from './schema'

export interface NoteEditorOptions {
  html: string
  /** Whether the reader may change the note; a note from a newer note editor
   *  is read-only whatever this says. */
  editable: boolean
  /** The words joining authors in a citation, in the interface's language. */
  words?: CitationWords
  /** Where an embedded image attachment's file is served. */
  imageUrl: (attachmentKey: string) => string
  placeholder?: string
  /** The text field's accessible name. */
  label?: string
  /** Called after each change the reader makes, never on loading. */
  onChange?: (html: string) => void
  toggleLink?: () => boolean
  focusToolbar?: () => boolean
  /** Behaviour the interface adds around the note, such as the "/" menu. */
  extensions?: AnyExtension[]
}

export interface NoteEditor {
  editor: Editor
  /** Written by a newer note editor than this one: shown, never saved. */
  unsupportedSchema: boolean
  /** The note as it would be saved now. */
  html: () => string
}

/** Addresses a link may send a reader to. */
export function safeHref(href: unknown): string | null {
  if (typeof href !== 'string') return null
  try {
    const url = new URL(href, window.location.href)
    return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : null
  } catch {
    return null
  }
}

function nodeViews(imageUrl: (key: string) => string): Record<string, (node: ProseMirrorNode) => NodeView> {
  return {
    heading: (node: ProseMirrorNode) => {
      const { dom, contentDOM } = DOMSerializer.renderSpec(document, node.type.spec.toDOM!(node))
      const element = dom as HTMLElement
      if (element.id) element.id = `user-content-${element.id}`
      return { dom, contentDOM }
    },
    image: (node: ProseMirrorNode) => {
      const img = document.createElement('img')
      img.alt = node.attrs.alt ?? ''
      if (node.attrs.title) img.title = node.attrs.title
      if (node.attrs.width) img.width = node.attrs.width
      if (node.attrs.height) img.height = node.attrs.height
      const src: string | null = node.attrs.src
      if (node.attrs.attachmentKey) {
        img.src = imageUrl(node.attrs.attachmentKey)
      } else if (src?.startsWith('data:image/')) {
        img.src = src
      }
      img.className = 'note-image'
      return { dom: img }
    },
  }
}

export function createNoteEditor(options: NoteEditorOptions): NoteEditor {
  const loaded = parseNote(noteSchema(), options.html, {
    editable: options.editable,
    words: options.words,
  })
  const metadata: Metadata = loaded.metadata
  const editable = options.editable && !loaded.unsupportedSchema

  const views = nodeViews(options.imageUrl)
  const editor = new Editor({
    content: loaded.doc.toJSON(),
    editable,
    // Its stylesheet is in `editor.css`; injected, the policy would refuse it.
    injectCSS: false,
    // Its Enter and Backspace would answer before the note editor's own.
    enableCoreExtensions: { keymap: false },
    extensions: [
      ...noteSchemaExtensions().map(extension => {
        const view = Object.hasOwn(views, extension.name) ? views[extension.name] : undefined
        return view && extension.type === 'node'
          ? (extension as Node).extend({ addNodeView: () => ({ node }) => view(node) })
          : extension
      }),
      NoteBehaviour.configure({
        toggleLink: options.toggleLink ?? (() => false),
        focusToolbar: options.focusToolbar ?? (() => false),
        smartQuotes: true,
      }),
      Dropcursor,
      Gapcursor,
      Placeholder.configure({ placeholder: options.placeholder ?? '' }),
      ...(options.extensions ?? []),
    ],
    // A citation's text is written from the note's metadata, which has to be
    // on the schema before the view first draws it.
    onBeforeCreate: ({ editor }) => setNoteContext(editor.schema, metadata, options.words),
    onUpdate: ({ editor }) => {
      if (editor.isEditable) options.onChange?.(serializeNote(editor.state.doc.content, metadata))
    },
    editorProps: {
      // Room under the cursor for a toolbar docked on a phone's keyboard,
      // so the line being typed never scrolls behind it.
      scrollMargin: { top: 8, right: 8, bottom: 72, left: 8 },
      scrollThreshold: { top: 8, right: 8, bottom: 72, left: 8 },
      // The element that takes the text is a multi-line text field, and a
      // field needs a name (WCAG 4.1.2).
      attributes: {
        role: 'textbox',
        'aria-multiline': 'true',
        ...(options.label ? { 'aria-label': options.label } : {}),
      },
      handleDOMEvents: {
        // Never the browser's own navigation, which would follow any scheme
        // a note was given; the toolbar's link popup opens what is safe.
        click: (_, event) => {
          if ((event.target as Element | null)?.closest?.('a')) event.preventDefault()
          return false
        },
      },
    },
  })

  return {
    editor,
    unsupportedSchema: loaded.unsupportedSchema,
    html: () => serializeNote(editor.state.doc.content, metadata),
  }
}
