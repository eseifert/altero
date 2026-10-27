/**
 * The nodes of Zotero's note schema, as ProseMirror specs.
 *
 * Ported from zotero/note-editor `src/core/schema/nodes.js` at `acec74d`, the
 * revision Zotero pins as its submodule, and kept as close to it as TypeScript
 * allows so the two can be compared line by line. Every parse rule and every
 * `toDOM` is the original's: the HTML a note is saved as must be the HTML the
 * desktop would have saved, or a note edited here comes back to the desktop
 * changed in ways nobody asked for. `schema.ts` turns these into Tiptap
 * extensions.
 *
 * Left out are `nodeID`, `originalSrc` and `tempSrc` on images and `nodeID` and
 * `version` on citations: the desktop's own bookkeeping for pasting and
 * importing, never written into a note.
 */
import { Fragment, type NodeSpec } from '@tiptap/pm/model'

import { decodeObject, encodeObject } from './citations'
import { serializeCitationInnerHTML } from './context'

// Schema does not limit the indent level for the compatibility with the old
// notes, although the UI doesn't allow to set higher than MAX_INDENT values.
export const MAX_INDENT = 7

function getInteger(value: string | null): number | null {
  if (value) {
    const number = parseInt(value)
    if (!isNaN(number)) {
      return number
    }
  }
  return null
}

function style(styles: Record<string, string | null | undefined>): string | null {
  const list = []
  for (const styleName in styles) {
    if (styles[styleName]) {
      list.push(`${styleName}: ${styles[styleName]}`)
    }
  }
  return (list.length && list.join(';')) || null
}

// `padding-left` / `padding-right` style attributes are converted to `data-indent`
function getIndent(dom: HTMLElement): number | null {
  const INDENT_WIDTH = 40 // TinyMCE padding width for a single indent
  const value = dom.style.paddingLeft || dom.style.paddingRight
  const num = parseInt(value)
  if (Number.isInteger(num) && num + 'px' === value && num > 0 && num % INDENT_WIDTH === 0) {
    return num / INDENT_WIDTH
  }

  const attribute = dom.getAttribute('data-indent')
  if (attribute) {
    const indent = parseInt(attribute)
    if (Number.isInteger(indent) && indent >= 1) {
      return indent
    }
  }

  return null
}

function getAlign(dom: HTMLElement): string | null {
  const value = dom.style.textAlign
  if (value) {
    const align = value.toLowerCase()
    // 'justify' doesn't work on FF (works on Chrome), although it's still
    // preserved, because the old editor had it
    if (['left', 'right', 'center', 'justify'].includes(align)) {
      return align
    }
  }
  return null
}

function getDir(dom: HTMLElement): string | null {
  const value = dom.dir
  if (value) {
    const dir = value.toLowerCase()
    if (['ltr', 'rtl'].includes(dir)) {
      return dir
    }
  }
  return null
}

/**
 * The note editor reads `window.dir`, which Zotero sets to the direction of
 * its interface. Here that is the page's own.
 */
function interfaceDirection(): string {
  return typeof document === 'undefined' ? 'ltr' : document.documentElement.dir
}

function backCompIndent(node: { attrs: Record<string, any> }): Record<string, string> {
  const INDENT_WIDTH = 40
  if (node.attrs.indent) {
    const dir = node.attrs.dir || interfaceDirection()
    if (dir === 'rtl') {
      return { 'padding-right': node.attrs.indent * INDENT_WIDTH + 'px' }
    } else {
      return { 'padding-left': node.attrs.indent * INDENT_WIDTH + 'px' }
    }
  }
  return {}
}

function migrateAnnotationURI(annotation: any): void {
  // Migrate annotation.uri to annotation.attachmentURI which was used until v4
  if (annotation && annotation.uri) {
    annotation.attachmentURI = annotation.uri
    delete annotation.uri
  }
}

// The cell attributes `prosemirror-tables` gives its `tableNodes`, with the
// one extra the note editor asks it for.
const cellAttrs = {
  colspan: { default: 1, validate: 'number' },
  rowspan: { default: 1, validate: 'number' },
  colwidth: { default: null },
  background: { default: null },
}

function getCellAttrs(dom: HTMLElement): Record<string, unknown> {
  const widthAttr = dom.getAttribute('data-colwidth')
  const widths =
    widthAttr && /^\d+(,\d+)*$/.test(widthAttr) ? widthAttr.split(',').map(s => Number(s)) : null
  const colspan = Number(dom.getAttribute('colspan') || 1)
  const result: Record<string, unknown> = {
    colspan,
    rowspan: Number(dom.getAttribute('rowspan') || 1),
    colwidth: widths && widths.length == colspan ? widths : null,
  }
  const background = dom.style.backgroundColor || null
  if (background != null) result.background = background
  return result
}

function setCellAttrs(node: { attrs: Record<string, any> }): Record<string, string> {
  const attrs: Record<string, string> = {}
  if (node.attrs.colspan != 1) attrs.colspan = node.attrs.colspan
  if (node.attrs.rowspan != 1) attrs.rowspan = node.attrs.rowspan
  if (node.attrs.colwidth) attrs['data-colwidth'] = node.attrs.colwidth.join(',')
  if (node.attrs.background) {
    attrs.style = (attrs.style || '') + `background-color: ${node.attrs.background};`
  }
  return attrs
}

export const nodes: Record<string, NodeSpec> = {
  doc: {
    content: 'block+',
  },

  // Block nodes
  paragraph: {
    group: 'block',
    content: '(text | hardBreak | image | citation | highlight | underline_annotation | math_inline)*',
    attrs: {
      indent: { default: null },
      align: { default: null },
      dir: { default: null },
    },
    parseDOM: [
      {
        tag: 'p',
        getAttrs: dom => ({
          indent: getIndent(dom),
          align: getAlign(dom),
          dir: getDir(dom),
        }),
      },
      { tag: 'dd' },
    ],
    toDOM: node => [
      'p',
      {
        style: style({ 'text-align': node.attrs.align, ...backCompIndent(node) }),
        dir: node.attrs.dir,
        'data-indent': node.attrs.indent,
      },
      0,
    ],
  },

  heading: {
    content: '(text | hardBreak | citation | highlight | underline_annotation)*',
    group: 'block',
    defining: true,
    attrs: {
      level: { default: 1 },
      indent: { default: null },
      align: { default: null },
      dir: { default: null },
      id: { default: null },
    },
    parseDOM: [1, 2, 3, 4, 5, 6].map(level => ({
      tag: 'h' + level,
      getAttrs: (dom: HTMLElement) => ({
        level,
        id: dom.getAttribute('id'),
        dir: getDir(dom),
        indent: getIndent(dom),
        align: getAlign(dom),
      }),
    })),
    toDOM: node => [
      'h' + node.attrs.level,
      {
        style: style({ 'text-align': node.attrs.align, ...backCompIndent(node) }),
        id: node.attrs.id,
        dir: node.attrs.dir,
        'data-indent': node.attrs.indent,
      },
      0,
    ],
  },

  math_display: {
    group: 'block math',
    content: 'text*',
    atom: true,
    code: true,
    toDOM: node => ['pre', { class: 'math' }, '$$' + node.textContent + '$$'],
    parseDOM: [
      {
        tag: 'pre.math',
        getContent(dom, schema) {
          let text = (dom.textContent ?? '').trim()
          if (text.slice(0, 2) === '$$' && text.slice(-2) === '$$') {
            text = text.slice(2, -2)
          }
          return text.length ? Fragment.from(schema.text(text)) : Fragment.empty
        },
      },
    ],
  },

  codeBlock: {
    group: 'block',
    content: 'text*',
    marks: 'strong em underline strike subsup textColor backgroundColor link',
    code: true,
    defining: true,
    attrs: {
      dir: { default: null },
      indent: { default: null },
    },
    parseDOM: [
      {
        tag: 'pre',
        preserveWhitespace: 'full',
        getAttrs: dom => ({
          dir: getDir(dom),
          indent: getIndent(dom),
        }),
      },
    ],
    toDOM: node => [
      'pre',
      {
        style: style({ ...backCompIndent(node) }),
        dir: node.attrs.dir,
        'data-indent': node.attrs.indent,
      },
      0,
    ],
  },

  blockquote: {
    content: 'block+',
    group: 'block',
    defining: true,
    parseDOM: [{ tag: 'blockquote' }],
    toDOM: () => ['blockquote', 0],
  },

  horizontalRule: {
    group: 'block',
    parseDOM: [{ tag: 'hr' }],
    toDOM: () => ['hr'],
  },

  orderedList: {
    group: 'block',
    content: 'listItem+',
    attrs: {
      order: { default: 1 },
      dir: { default: null },
    },
    parseDOM: [
      {
        tag: 'ol',
        getAttrs: dom => ({
          order: dom.hasAttribute('start') ? +dom.getAttribute('start')! : 1,
          dir: getDir(dom),
        }),
      },
    ],
    toDOM: node =>
      node.attrs.order === 1
        ? ['ol', { dir: node.attrs.dir }, 0]
        : ['ol', { start: node.attrs.order, dir: node.attrs.dir }, 0],
  },

  bulletList: {
    group: 'block',
    content: 'listItem+',
    attrs: {
      dir: { default: null },
    },
    parseDOM: [
      {
        tag: 'ul',
        getAttrs: dom => ({ dir: getDir(dom) }),
      },
    ],
    toDOM: node => ['ul', { dir: node.attrs.dir }, 0],
  },

  // When joining list items two paragraphs appear
  listItem: {
    content: 'block+',
    defining: true,
    parseDOM: [{ tag: 'li' }],
    toDOM: () => ['li', 0],
  },

  // `tableNodes({ tableGroup: 'block', cellContent: 'block+', cellAttributes:
  // { background } })` from prosemirror-tables, spelled out.
  table: {
    content: 'table_row+',
    tableRole: 'table',
    isolating: true,
    group: 'block',
    parseDOM: [{ tag: 'table' }],
    toDOM: () => ['table', ['tbody', 0]],
  },

  table_row: {
    content: '(table_cell | table_header)*',
    tableRole: 'row',
    parseDOM: [{ tag: 'tr' }],
    toDOM: () => ['tr', 0],
  },

  table_cell: {
    content: 'block+',
    attrs: cellAttrs,
    tableRole: 'cell',
    isolating: true,
    parseDOM: [{ tag: 'td', getAttrs: dom => getCellAttrs(dom) }],
    toDOM: node => ['td', setCellAttrs(node), 0],
  },

  table_header: {
    content: 'block+',
    attrs: cellAttrs,
    tableRole: 'header_cell',
    isolating: true,
    parseDOM: [{ tag: 'th', getAttrs: dom => getCellAttrs(dom) }],
    toDOM: node => ['th', setCellAttrs(node), 0],
  },

  // Inline nodes

  // The original's `toDOM` here writes every second space of a run as a
  // non-breaking one, which TinyMCE needed. prosemirror-model no longer asks a
  // text node's `toDOM`, so `serializeNote` in `html.ts` does it instead.
  text: {
    group: 'inline',
  },

  hardBreak: {
    inline: true,
    group: 'inline',
    selectable: false,
    parseDOM: [{ tag: 'br' }],
    toDOM: () => ['br'],
  },

  image: {
    group: 'inline',
    inline: true,
    draggable: true,
    attrs: {
      src: { default: null },
      // It's recommended to always have alt attribute
      alt: { default: '' },
      title: { default: null },
      width: { default: null },
      height: { default: null },
      attachmentKey: { default: null },
      annotation: { default: null },
    },
    parseDOM: [
      {
        tag: 'img',
        getAttrs: dom => {
          const annotation = decodeObject(dom.getAttribute('data-annotation'))
          migrateAnnotationURI(annotation)
          return {
            src: dom.getAttribute('src'),
            alt: dom.getAttribute('alt') || '',
            title: dom.getAttribute('title'),
            width: getInteger(dom.getAttribute('width')),
            height: getInteger(dom.getAttribute('height')),
            attachmentKey: dom.getAttribute('data-attachment-key'),
            annotation,
          }
        },
      },
    ],
    toDOM: node => [
      'img',
      {
        src: node.attrs.src,
        alt: node.attrs.alt,
        title: node.attrs.title,
        width: node.attrs.width,
        height: node.attrs.height,
        'data-attachment-key': node.attrs.attachmentKey,
        'data-annotation': node.attrs.annotation && encodeObject(node.attrs.annotation),
      },
    ],
  },

  citation: {
    inline: true,
    group: 'inline',
    draggable: true,
    atom: true,
    selectable: true,
    attrs: {
      citation: { default: null },
    },
    parseDOM: [
      {
        tag: 'span.citation',
        getAttrs: dom => ({
          citation: decodeObject(dom.getAttribute('data-citation')) || {
            citationItems: [],
            properties: {},
          },
        }),
      },
    ],
    toDOM: node => [
      'span',
      { class: 'citation', 'data-citation': encodeObject(node.attrs.citation) },
      ...serializeCitationInnerHTML(node),
    ],
  },

  highlight: {
    inline: true,
    group: 'inline',
    content: '(text | hardBreak)*',
    defining: true,
    attrs: {
      annotation: { default: null },
    },
    parseDOM: [
      {
        tag: 'span.highlight',
        getAttrs: dom => {
          const annotation = decodeObject(dom.getAttribute('data-annotation'))
          if (annotation) {
            // Removes `text` property encountered in pre-v3 schema
            delete annotation.text
            migrateAnnotationURI(annotation)
            return { annotation }
          }
          return false
        },
      },
    ],
    toDOM: node => [
      'span',
      { class: 'highlight', 'data-annotation': encodeObject(node.attrs.annotation) },
      0,
    ],
  },

  underline_annotation: {
    inline: true,
    group: 'inline',
    content: '(text | hardBreak)*',
    defining: true,
    attrs: {
      annotation: { default: null },
    },
    parseDOM: [
      {
        tag: 'span.underline',
        getAttrs: dom => {
          const annotation = decodeObject(dom.getAttribute('data-annotation'))
          if (annotation) {
            return { annotation }
          }
          return false
        },
      },
    ],
    toDOM: node => [
      'span',
      { class: 'underline', 'data-annotation': encodeObject(node.attrs.annotation) },
      0,
    ],
  },

  math_inline: {
    group: 'inline math',
    content: 'text*',
    marks: '',
    inline: true,
    atom: true,
    toDOM: node => ['span', { class: 'math' }, '$' + node.textContent + '$'],
    parseDOM: [
      {
        tag: 'span.math',
        getContent(dom, schema) {
          let text = (dom.textContent ?? '').trim()
          if (text.slice(0, 1) === '$' && text.slice(-1) === '$') {
            text = text.slice(1, -1)
          }
          return text.length ? Fragment.from(schema.text(text)) : Fragment.empty
        },
      },
    ],
  },
}
