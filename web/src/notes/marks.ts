/**
 * The marks of Zotero's note schema, as ProseMirror specs.
 *
 * Ported from zotero/note-editor `src/core/schema/marks.js` at `acec74d`, under
 * the same rule as `nodes.ts`: every parse rule and `toDOM` is the original's.
 */
import type { MarkSpec } from '@tiptap/pm/model'

/** `HIGHLIGHT_COLORS` from the note editor's `colors.js`. */
export const HIGHLIGHT_COLORS: readonly (readonly [string, string])[] = [
  ['red', '#ff666680'],
  ['orange', '#f1983780'],
  ['yellow', '#ffd40080'],
  ['green', '#5fb23680'],
  ['purple', '#a28ae580'],
  ['magenta', '#e56eee80'],
  ['blue', '#2ea8e580'],
  ['gray', '#aaaaaa80'],
]

/** `TEXT_COLORS` from the note editor's `colors.js`. */
export const TEXT_COLORS: readonly (readonly [string, string])[] = [
  ['red', '#ff2020'],
  ['orange', '#ff7700'],
  ['yellow', '#ffcb00'],
  ['green', '#4eb31c'],
  ['purple', '#7953e3'],
  ['magenta', '#eb52f7'],
  ['blue', '#05a2ef'],
  ['gray', '#7e8386'],
]

export const marks: Record<string, MarkSpec> = {
  strong: {
    inclusive: true,
    parseDOM: [
      { tag: 'strong' },
      // From ProseMirror source: This works around a Google Docs misbehavior
      // where pasted content will be inexplicably wrapped in `<b>` tags with a
      // font-weight normal.
      {
        tag: 'b',
        getAttrs: dom => dom.style.fontWeight !== 'normal' && null,
      },
      {
        style: 'font-weight',
        getAttrs: value => /^(bold(er)?|[5-9]\d{2,})$/.test(value) && null,
      },
      { tag: 'dt' },
    ],
    toDOM: () => ['strong', 0],
  },

  em: {
    inclusive: true,
    parseDOM: [
      { tag: 'i' },
      { tag: 'em' },
      { style: 'font-style=italic' },
      { tag: 'cite' },
      { tag: 'dfn' },
      { tag: 'q' },
    ],
    toDOM: () => ['em', 0],
  },

  underline: {
    inclusive: true,
    attrs: {
      color: { default: '' },
    },
    parseDOM: [
      {
        tag: 'u',
        getAttrs: dom => {
          const color = dom.style.getPropertyValue('text-decoration-color') || ''
          return { color }
        },
      },
      { style: 'text-decoration=underline' },
      { style: 'text-decoration-line=underline' },
    ],
    toDOM: mark => {
      let style
      if (mark.attrs.color) {
        style = `text-decoration-color: ${mark.attrs.color};`
      }
      return ['u', { style }, 0]
    },
  },

  strike: {
    inclusive: true,
    parseDOM: [
      { tag: 's' },
      { tag: 'strike' },
      { tag: 'del' },
      { style: 'text-decoration=line-through' },
      { style: 'text-decoration-line=line-through' },
    ],
    // Unfortunately Zotero TinyMCE doesn't support <s>
    toDOM: () => ['span', { style: 'text-decoration: line-through' }, 0],
  },

  subsup: {
    inclusive: true,
    attrs: { type: { default: 'sub' } },
    parseDOM: [
      { tag: 'sub', attrs: { type: 'sub' } },
      { style: 'vertical-align=sub', attrs: { type: 'sub' } },
      { tag: 'sup', attrs: { type: 'sup' } },
      { style: 'vertical-align=super', attrs: { type: 'sup' } },
    ],
    toDOM: mark => [mark.attrs.type],
  },

  textColor: {
    inclusive: true,
    attrs: { color: {} },
    parseDOM: [
      {
        style: 'color',
        getAttrs: value => ({ color: value }),
      },
    ],
    toDOM: mark => ['span', { style: `color: ${mark.attrs.color}` }, 0],
  },

  backgroundColor: {
    inclusive: true,
    attrs: { color: {} },
    parseDOM: [
      {
        style: 'background-color',
        getAttrs: value => {
          let color = value
          if (color) {
            color = color.toLowerCase()
            // Add 50% opacity if it has one of highlight colors
            if (HIGHLIGHT_COLORS.map(x => x[1].slice(0, 7)).includes(color)) {
              color += '80'
            }
          }
          return { color }
        },
      },
      {
        style: 'background',
        getAttrs: value => (value.split(' ').length === 1 ? { color: value } : false),
      },
    ],
    toDOM: mark => ['span', { style: `background-color: ${mark.attrs.color}` }, 0],
  },

  link: {
    inclusive: false,
    attrs: {
      href: {},
      title: { default: null },
    },
    parseDOM: [
      {
        tag: 'a[href]',
        getAttrs: dom => ({
          href: dom.getAttribute('href'),
          title: dom.getAttribute('title'),
        }),
      },
    ],
    toDOM: mark => ['a', { ...mark.attrs, rel: 'noopener noreferrer nofollow' }, 0],
  },

  // Additional constraints are applied through transformations
  code: {
    excludes: '_',
    inclusive: true,
    parseDOM: [
      { tag: 'code', preserveWhitespace: true },
      { tag: 'tt', preserveWhitespace: true },
      { tag: 'kbd', preserveWhitespace: true },
      { tag: 'samp', preserveWhitespace: true },
      { tag: 'var', preserveWhitespace: true },
      {
        style: 'font-family',
        preserveWhitespace: true,
        getAttrs: value => value.toLowerCase().indexOf('monospace') > -1 && null,
      },
      { style: 'white-space=pre', preserveWhitespace: true },
    ],
    toDOM: () => ['code', 0],
  },
}
