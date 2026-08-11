/**
 * Icons for the rows of a sidebar — the library's, and settings' — and for the
 * handful of controls elsewhere that are a glyph and nothing else: the tools
 * over the item list, and the path a dialog shows.
 *
 * The library's are drawn to read like the Zotero desktop application's
 * sidebar: a stack of books for a library, two figures for a group, a folder
 * for a collection, a bin for the trash. As with the item type icons, they are
 * redrawn as single-weight line glyphs on the same 24-unit grid rather than
 * copied — Zotero's own assets are the client's and carry its licence.
 *
 * Settings has no counterpart in the client, so those glyphs are only drawn to
 * the same rules: one weight, one grid, no fill.
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

  /** A page with a globe beside it: the part of a library that is published. */
  publications: {
    label: 'My Publications',
    paths: [
      'M6.75 19.25V4.75h5.5l4 3.75v3.5',
      'M12.25 4.75V8.5h4',
      'M6.75 19.25h4',
      'M15.5 19.75a3.25 3.25 0 100-6.5 3.25 3.25 0 000 6.5z',
      'M12.25 16.5h6.5',
      'M15.5 13.25c.95 1 1.45 2.1 1.45 3.25s-.5 2.25-1.45 3.25c-.95-1-1.45-2.1-1.45-3.25s.5-2.25 1.45-3.25z',
    ],
  },

  /** A clock, for what has been opened lately. */
  recent: {
    label: 'Recently Read',
    paths: ['M12 20.25a8.25 8.25 0 100-16.5 8.25 8.25 0 000 16.5z', 'M12 7.25V12l3 2'],
  },

  /** Two pages, one behind the other: the same thing twice. */
  duplicates: {
    label: 'Duplicate Items',
    paths: [
      'M9.75 3.75h5L18.25 7v9.25H9.75z M14.75 3.75V7h3.5',
      'M6.75 7.5v12.75h9',
    ],
  },

  /** An open folder with nothing in it: filed nowhere. */
  unfiled: {
    label: 'Unfiled Items',
    paths: [
      'M3.75 6.75A1.5 1.5 0 015.25 5.25h3.9l1.8 2.25h7.8a1.5 1.5 0 011.5 1.5v1.25H3.75z',
      'M3.75 10.25l1.6 7.7a1.5 1.5 0 001.47 1.3h10.36a1.5 1.5 0 001.47-1.3l1.6-7.7',
    ],
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

  /* ---- The tools over the item list, and the ones beside an item ---- */

  /** A ticked box: picking rows out, which is what the mode draws on each. */
  select: {
    label: 'Select',
    paths: [
      'M5.75 4.75h12.5a1 1 0 011 1v12.5a1 1 0 01-1 1H5.75a1 1 0 01-1-1V5.75a1 1 0 011-1z',
      'M8.5 12.15l2.4 2.4 4.6-5.1',
    ],
  },

  /** Something leaving a tray: an item written out of the library as a file.
   *  Not the settings box, which is a whole library packed up to be carried. */
  export: {
    label: 'Export',
    paths: [
      'M12 15V4.75',
      'M8.5 8.25L12 4.75l3.5 3.5',
      'M4.75 14.75v3.5a1.5 1.5 0 001.5 1.5h11.5a1.5 1.5 0 001.5-1.5v-3.5',
    ],
  },

  /** An arrow going into a folder: filing something, or copying it elsewhere. */
  move: {
    label: 'Move or copy',
    paths: [
      'M3.75 12.5h6.5',
      'M8.25 10.25l2.25 2.25-2.25 2.25',
      'M13.25 7.25h2.4l1.1 1.4h3a.9.9 0 01.9.9v6.9a.9.9 0 01-.9.9h-6.5a.9.9 0 01-.9-.9V8.15a.9.9 0 01.9-.9z',
    ],
  },

  /** An arrow curving back on itself: out of the trash, where it came from. */
  restore: {
    label: 'Restore to Library',
    paths: [
      'M4.75 12a7.25 7.25 0 107.25-7.25 7.2 7.2 0 00-5.55 2.6',
      'M4.75 4.75v3.5h3.5',
    ],
  },

  /** The bin again, with a cross through what is in it: gone for good, which
   *  is a different act from putting something in the trash. */
  deleteforever: {
    label: 'Delete',
    paths: [
      'M4.75 7.25h14.5',
      'M9.5 7.25V5.5a1.25 1.25 0 011.25-1.25h2.5A1.25 1.25 0 0114.5 5.5v1.75',
      'M6.75 7.25l.9 11.4a1.5 1.5 0 001.5 1.35h5.7a1.5 1.5 0 001.5-1.35l.9-11.4',
      'M10.15 11.1l3.7 4.4 M13.85 11.1l-3.7 4.4',
    ],
  },

  /** The published page with a plus, and with a minus: the two directions of
   *  one errand, which a glyph has to show since it cannot say them. */
  publish: {
    label: 'Add to My Publications',
    paths: [
      'M6.75 18.25V4.75h5.25l3.75 3.45v2.55',
      'M12 4.75V8.5h3.75',
      'M6.75 18.25h4.5',
      'M16.75 14.25v5.5 M14 17h5.5',
    ],
  },

  unpublish: {
    label: 'Remove from My Publications',
    paths: [
      'M6.75 18.25V4.75h5.25l3.75 3.45v2.55',
      'M12 4.75V8.5h3.75',
      'M6.75 18.25h4.5',
      'M14 17h5.5',
    ],
  },

  /* ---- The settings sidebar ---- */

  /** A head and shoulders: the account itself. */
  account: {
    label: 'Profile',
    paths: [
      'M12 12.25a3.25 3.25 0 100-6.5 3.25 3.25 0 000 6.5z',
      'M5.75 19.25c0-3.15 2.8-5.5 6.25-5.5s6.25 2.35 6.25 5.5',
    ],
  },

  /** A padlock, shackle closed. */
  security: {
    label: 'Sign-in and security',
    paths: [
      'M6.75 10.75h10.5a1.25 1.25 0 011.25 1.25v6a1.25 1.25 0 01-1.25 1.25H6.75A1.25 1.25 0 015.5 18v-6a1.25 1.25 0 011.25-1.25z',
      'M8.75 10.75V8.25a3.25 3.25 0 016.5 0v2.5',
    ],
  },

  /** A globe with a meridian, for the language and the zone alike. */
  language: {
    label: 'Language and time zone',
    paths: [
      'M12 20.25a8.25 8.25 0 100-16.5 8.25 8.25 0 000 16.5z',
      'M3.75 12h16.5',
      'M12 3.75c2.1 2.2 3.25 5.15 3.25 8.25S14.1 18.05 12 20.25c-2.1-2.2-3.25-5.15-3.25-8.25S9.9 5.95 12 3.75z',
    ],
  },

  /** A key: the bow on the left, two teeth at the tip. */
  keys: {
    label: 'API keys',
    paths: [
      'M9.25 15.75a3.75 3.75 0 100-7.5 3.75 3.75 0 000 7.5z',
      'M12.9 11.35l6.35-.85',
      'M16.15 10.9l.3 2.2 M18.6 10.55l.3 2.2',
    ],
  },

  /* ---- The administration sidebar ---- */

  /** Two racked units with a light apiece: the server itself. */
  server: {
    label: 'Overview',
    paths: [
      'M5.75 5.25h12.5a1 1 0 011 1v3.5a1 1 0 01-1 1H5.75a1 1 0 01-1-1v-3.5a1 1 0 011-1z',
      'M5.75 13.25h12.5a1 1 0 011 1v3.5a1 1 0 01-1 1H5.75a1 1 0 01-1-1v-3.5a1 1 0 011-1z',
      'M8 8h.01 M8 16h.01',
    ],
  },

  /** A platter seen edge on: what the attachments weigh. */
  disk: {
    label: 'Storage',
    paths: [
      'M19.25 7c0 1.24-3.25 2.25-7.25 2.25S4.75 8.24 4.75 7 8 4.75 12 4.75 19.25 5.76 19.25 7z',
      'M4.75 7v10c0 1.24 3.25 2.25 7.25 2.25s7.25-1.01 7.25-2.25V7',
      'M19.25 12c0 1.24-3.25 2.25-7.25 2.25S4.75 13.24 4.75 12',
    ],
  },

  /** A box with its lid: a library packed up to be carried somewhere. */
  archive: {
    label: 'Import and export',
    paths: [
      'M4.75 6.75h14.5v3H4.75z',
      'M6.25 9.75v8a1.5 1.5 0 001.5 1.5h8.5a1.5 1.5 0 001.5-1.5v-8',
      'M10 13.25h4',
    ],
  },
}

export const FALLBACK_SIDEBAR_ICON = 'collection'

export function sidebarIcon(name: string): ItemIcon {
  return SIDEBAR_ICONS[name] ?? SIDEBAR_ICONS[FALLBACK_SIDEBAR_ICON]
}
