/**
 * Item type icons.
 *
 * Drawn to read like the Zotero desktop application's: the same silhouettes --
 * a closed book, a page of text, a globe for a web page, a yellow-note shape
 * for a note -- redrawn as single-weight line glyphs on a 24-unit grid so they
 * sit with the rest of the interface. They are not copies of Zotero's own
 * assets, which are the client's and carry its licence.
 *
 * Every type the schema declares has an entry; `iconFor` falls back to the
 * generic document so that a server whose schema is newer than this build
 * renders something rather than a blank row.
 */

export interface ItemIcon {
  /** SVG path data, drawn on a 0 0 24 24 viewBox. */
  paths: string[]
  /** Human name, used as the accessible label and in tooltips. */
  label: string
}

/* ---- Shared silhouettes, so related types stay visibly related. ---- */

/** A page with a folded corner: the base for every document-ish type. */
const PAGE = 'M6 2.75h7L18.25 8v13.25H6z M13 2.75V8h5.25'

/** Lines of text inside a page. */
const PAGE_LINES = `${PAGE} M8.75 12h6.5 M8.75 15h6.5 M8.75 18h4`

/** A closed book seen from the spine side. */
const BOOK = 'M5 3.75h11.5a2 2 0 012 2v14.5H7a2 2 0 01-2-2z M7 20.25a2 2 0 010-4h11.5'

const SCREEN = 'M2.75 4.75h18.5v12H2.75z M8 20.25h8 M12 16.75v3.5'

export const ITEM_TYPE_ICONS: Record<string, ItemIcon> = {
  /* ---- Books and parts of books ---- */
  book: { label: 'Book', paths: [BOOK] },
  bookSection: {
    label: 'Book section',
    paths: [BOOK, 'M10 7.75h5.5 M10 10.75h3.5'],
  },
  dictionaryEntry: { label: 'Dictionary entry', paths: [BOOK, 'M10 7.75h5.5 M10 10.75h2'] },
  encyclopediaArticle: {
    label: 'Encyclopedia article',
    paths: [BOOK, 'M9.5 7.75h6 M9.5 10.75h6 M9.5 13.75h4'],
  },

  /* ---- Articles and papers ---- */
  journalArticle: { label: 'Journal article', paths: [PAGE_LINES] },
  magazineArticle: { label: 'Magazine article', paths: [PAGE, 'M8.75 11.5h6.5v4h-6.5z M8.75 18h6.5'] },
  newspaperArticle: {
    label: 'Newspaper article',
    paths: ['M3.75 5.75h13.5v14H5.75a2 2 0 01-2-2z M17.25 8.75h3v9a2 2 0 01-3 1.7 M6.5 8.75h8 M6.5 12h8 M6.5 15.25h5'],
  },
  conferencePaper: {
    label: 'Conference paper',
    paths: [PAGE_LINES, 'M3.5 5a3 3 0 013-2.25'],
  },
  preprint: { label: 'Preprint', paths: [PAGE, 'M8.75 12h6.5 M8.75 15h6.5 M8.75 18h4 M2.5 4.5l3 3'] },
  thesis: {
    label: 'Thesis',
    paths: [PAGE_LINES, 'M12 21.25v1.5 M10.25 21.75h3.5'],
  },
  manuscript: { label: 'Manuscript', paths: [PAGE, 'M8.75 12h6.5 M8.75 15h6.5 M8.75 18h4 M16.5 3.5l3.5 3.5-2 2'] },
  report: { label: 'Report', paths: [PAGE, 'M8.75 12h6.5 M8.75 15h4 M14 17.5l1.75 1.75 2.5-3'] },
  document: { label: 'Document', paths: [PAGE] },
  standard: { label: 'Standard', paths: [PAGE, 'M12 11.5l1.4 2.9 3.1.4-2.3 2.2.6 3.1-2.8-1.5-2.8 1.5.6-3.1-2.3-2.2 3.1-.4z'] },
  dataset: {
    label: 'Dataset',
    paths: ['M4.75 6.5c0-1.5 3.2-2.75 7.25-2.75S19.25 5 19.25 6.5 16 9.25 12 9.25 4.75 8 4.75 6.5z M4.75 6.5v11c0 1.5 3.2 2.75 7.25 2.75s7.25-1.25 7.25-2.75v-11 M4.75 12c0 1.5 3.2 2.75 7.25 2.75s7.25-1.25 7.25-2.75'],
  },
  computerProgram: {
    label: 'Computer program',
    paths: ['M9 8.75L5.25 12 9 15.25 M15 8.75L18.75 12 15 15.25 M2.75 4.75h18.5v14.5H2.75z'],
  },

  /* ---- The web ---- */
  webpage: {
    label: 'Web page',
    paths: ['M12 2.75a9.25 9.25 0 100 18.5 9.25 9.25 0 000-18.5z M2.9 9.5h18.2 M2.9 14.5h18.2 M12 2.75c-2.6 2.4-4 5.8-4 9.25s1.4 6.85 4 9.25 M12 2.75c2.6 2.4 4 5.8 4 9.25s-1.4 6.85-4 9.25'],
  },
  blogPost: {
    label: 'Blog post',
    paths: ['M4.75 4.75h14.5v14.5H4.75z M7.5 8.5h9 M7.5 12h9 M7.5 15.5h5.5'],
  },
  forumPost: {
    label: 'Forum post',
    paths: ['M3.75 4.75h16.5v11H9l-5.25 4.5z M7.5 8.5h9 M7.5 12h5.5'],
  },
  instantMessage: {
    label: 'Instant message',
    paths: ['M3.75 4.75h16.5v11H9l-5.25 4.5z M8 10.25h.01 M12 10.25h.01 M16 10.25h.01'],
  },
  email: {
    label: 'Email',
    paths: ['M2.75 5.75h18.5v12.5H2.75z M2.75 6.5L12 13l9.25-6.5'],
  },
  podcast: {
    label: 'Podcast',
    paths: ['M12 3.75a3 3 0 013 3v4.5a3 3 0 01-6 0v-4.5a3 3 0 013-3z M6.75 11.5a5.25 5.25 0 0010.5 0 M12 16.75v3.5 M9 20.25h6'],
  },

  /* ---- Recorded media ---- */
  film: {
    label: 'Film',
    paths: ['M2.75 4.75h18.5v14.5H2.75z M2.75 8.5h18.5 M2.75 15.5h18.5 M7 4.75v3.75 M17 4.75v3.75 M7 15.5v3.75 M17 15.5v3.75'],
  },
  videoRecording: {
    label: 'Video recording',
    paths: ['M2.75 6.75h11.5v10.5H2.75z M14.25 10.5l7-3.25v9.5l-7-3.25z'],
  },
  tvBroadcast: {
    label: 'TV broadcast',
    paths: [SCREEN, 'M8 2.25l4 2.5 4-2.5'],
  },
  radioBroadcast: {
    label: 'Radio broadcast',
    paths: ['M3.75 9.75h16.5v10.5H3.75z M7.75 15h.01 M11.5 13.25h5.5 M11.5 16.75h5.5 M18 3.5L7 9'],
  },
  audioRecording: {
    label: 'Audio recording',
    paths: ['M9.25 17.5a3.25 3.25 0 11-6.5 0 3.25 3.25 0 016.5 0z M21.25 15a3.25 3.25 0 11-6.5 0 3.25 3.25 0 016.5 0z M9.25 17.5V6.5l12-2.25V15'],
  },
  presentation: {
    label: 'Presentation',
    paths: [SCREEN, 'M7.5 13.5l3-3 2.5 2 3.5-4'],
  },
  interview: {
    label: 'Interview',
    paths: ['M12 3.75a2.5 2.5 0 012.5 2.5v4a2.5 2.5 0 01-5 0v-4a2.5 2.5 0 012.5-2.5z M6.75 11a5.25 5.25 0 0010.5 0 M12 16.25v4 M8.75 20.25h6.5'],
  },

  /* ---- Legal and official ---- */
  case: {
    label: 'Case',
    paths: ['M12 3.75v16.5 M6.75 20.25h10.5 M4 8.5h16 M4 8.5l-2.25 5.5h4.5z M20 8.5l-2.25 5.5h4.5z'],
  },
  statute: { label: 'Statute', paths: [PAGE, 'M8.75 12h6.5 M8.75 15h6.5 M8.75 18h4 M3 3l2.5 2.5'] },
  bill: { label: 'Bill', paths: [PAGE, 'M8.75 11.5h6.5 M8.75 14.5h6.5 M8.75 17.5h6.5'] },
  hearing: {
    label: 'Hearing',
    paths: ['M4.75 19.25h14.5 M6.75 19.25v-6.5h10.5v6.5 M12 12.75V8.5 M8.5 8.5h7 M12 4.25v4.25'],
  },
  patent: {
    label: 'Patent',
    paths: ['M12 2.75l2.6 5.4 5.9.85-4.25 4.2 1 5.9-5.25-2.8-5.25 2.8 1-5.9L3.5 9l5.9-.85z'],
  },

  /* ---- Correspondence, maps and pictures ---- */
  letter: {
    label: 'Letter',
    paths: ['M2.75 5.75h18.5v12.5H2.75z M2.75 6.5L12 13l9.25-6.5 M2.75 18.25L9 12 M21.25 18.25L15 12'],
  },
  map: {
    label: 'Map',
    paths: ['M2.75 6.5L9 4.25v13.25L2.75 19.75z M9 4.25l6 2.25v13.25L9 17.5 M15 6.5l6.25-2.25v13.25L15 19.75z'],
  },
  artwork: {
    label: 'Artwork',
    paths: ['M3.75 4.75h16.5v14.5H3.75z M3.75 16l4.5-4.5 3.5 3.5 3-3 5.5 5.5 M9 9.5a1.25 1.25 0 11-2.5 0 1.25 1.25 0 012.5 0z'],
  },

  /* ---- Zotero's own kinds, which are not bibliography at all ---- */
  note: {
    label: 'Note',
    paths: ['M5.75 3.75h12.5v11.5l-5 5H5.75z M18.25 15.25h-5v5 M8.75 8h6.5 M8.75 11.5h5'],
  },
  attachment: {
    label: 'Attachment',
    paths: ['M16.5 7.5l-7 7a2.5 2.5 0 003.5 3.5l7.5-7.5a4.5 4.5 0 00-6.5-6.25l-7.5 7.5a6.5 6.5 0 009.25 9.25'],
  },
  annotation: {
    label: 'Annotation',
    paths: [PAGE, 'M8.75 12.5h6.5 M8.75 15.5h3 M14 17l2 2 4-4.5'],
  },
}

/** The type used when the server names one this build does not know. */
export const FALLBACK_ITEM_TYPE = 'document'

export function iconFor(itemType: string): ItemIcon {
  return ITEM_TYPE_ICONS[itemType] ?? ITEM_TYPE_ICONS[FALLBACK_ITEM_TYPE]
}
