/**
 * Icons for the rows of the library sidebar.
 *
 * Drawn to read like the Zotero desktop application's sidebar: a stack of books
 * for a library, two figures for a group, a folder for a collection, a bin for
 * the trash. As with the item type icons, they are redrawn as single-weight line
 * glyphs on the same 24-unit grid rather than copied — Zotero's own assets are
 * the client's and carry its licence.
 *
 * `sidebarIcon` falls back to the folder, so a row this build has no glyph for
 * still lines up with the rest instead of jumping to the left.
 */

import type { ItemIcon } from './icons'

/** The folder every collection row uses, and the fallback for anything else. */
const FOLDER =
  'M3.75 6.75A1.5 1.5 0 015.25 5.25h3.9l1.8 2.25h7.8a1.5 1.5 0 011.5 1.5v8.25a1.5 1.5 0 01-1.5 1.5H5.25a1.5 1.5 0 01-1.5-1.5z'

export const SIDEBAR_ICONS: Record<string, ItemIcon> = {
  /** Three books standing on a shelf: a whole library. */
  library: {
    label: 'Library',
    paths: [
      'M4.75 4.75h3.5v14.5h-3.5z M10.25 4.75h3.5v14.5h-3.5z M15.75 5.5l3.4.9-3.6 13.6-2.3-.6z',
    ],
  },

  /** Two figures, as the client marks a group library. */
  group: {
    label: 'Group library',
    paths: [
      'M9.25 11a2.75 2.75 0 100-5.5 2.75 2.75 0 000 5.5z',
      'M3.75 19.25c0-2.9 2.5-5 5.5-5s5.5 2.1 5.5 5',
      'M16 6.1a2.75 2.75 0 010 5.3 M16.5 14.6c2.2.5 3.75 2.35 3.75 4.65',
    ],
  },

  /** Everything in the library, child items included: stacked pages. */
  everything: {
    label: 'All items',
    paths: ['M7.75 3.75h6L17.25 7v9.25H7.75z M13.75 3.75V7h3.5', 'M4.75 7.5v12.75h10.5'],
  },

  collection: { label: 'Collection', paths: [FOLDER] },

  /** A bin with its lid and two staves. */
  trash: {
    label: 'Trash',
    paths: [
      'M4.75 7.25h14.5',
      'M9.5 7.25V5.5a1.25 1.25 0 011.25-1.25h2.5A1.25 1.25 0 0114.5 5.5v1.75',
      'M6.75 7.25l.9 11.4a1.5 1.5 0 001.5 1.35h5.7a1.5 1.5 0 001.5-1.35l.9-11.4',
      'M10.5 10.75v6 M13.5 10.75v6',
    ],
  },

  /** A luggage-tag shape with its eyelet, for the tag list. */
  tag: {
    label: 'Tag',
    paths: [
      'M11.3 3.75H5.25A1.5 1.5 0 003.75 5.25v6.05a1.5 1.5 0 00.44 1.06l7.45 7.45a1.5 1.5 0 002.12 0l6.05-6.05a1.5 1.5 0 000-2.12l-7.45-7.45a1.5 1.5 0 00-1.06-.44z',
      'M7.75 8.25a.5.5 0 100-1 .5.5 0 000 1z',
    ],
  },
}

export const FALLBACK_SIDEBAR_ICON = 'collection'

export function sidebarIcon(name: string): ItemIcon {
  return SIDEBAR_ICONS[name] ?? SIDEBAR_ICONS[FALLBACK_SIDEBAR_ICON]
}
