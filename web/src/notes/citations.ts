/**
 * The JSON a note carries in its attributes, and the text a citation shows.
 *
 * Ported from zotero/note-editor `src/core/utils.js` at `acec74d`, the revision
 * Zotero pins as its submodule. A citation's visible text is not stored as the
 * truth: the note editor formats it again from the item data every time it
 * writes a note, so the words joining two authors are those of whoever saved
 * last. They are passed in here rather than read from a global.
 */

/** CSL-JSON, as far as a citation's text reads it. */
export interface CitationItemData {
  author?: { family?: string; literal?: string }[]
  title?: string
  issued?: { 'date-parts'?: (string | number)[][] }
  [field: string]: unknown
}

export interface CitationItem {
  uris: string[]
  itemData?: CitationItemData
  locator?: string
  label?: string
  prefix?: string
  suffix?: string
  [property: string]: unknown
}

export interface Citation {
  citationItems: CitationItem[]
  properties: Record<string, unknown>
  [property: string]: unknown
}

/** Zotero's `general-and` and `general-et-al`, in the language saving the note. */
export interface CitationWords {
  and: string
  etAl: string
}

export const ENGLISH_CITATION_WORDS: CitationWords = { and: 'and', etAl: 'et al.' }

export function encodeObject(value: unknown): string | null {
  if (typeof value !== 'object') {
    return null
  }
  return encodeURIComponent(JSON.stringify(value))
}

export function decodeObject(value: string | null): any {
  try {
    return JSON.parse(decodeURIComponent(value ?? ''))
  } catch {
    return null
  }
}

const STARTSWITH_ROMANESQUE_REGEXP =
  /^[&a-zA-Zก-๛À-ſͰ-ϿЀ-ԯ֐-הז-׿ἀ-῿؀-ۿ‌‍‎ȘșȚț‪-‮]/
const ENDSWITH_ROMANESQUE_REGEXP =
  /[.;:&a-zA-Zก-๛À-ſͰ-ϿЀ-ԯ֐-הז-׿ἀ-῿؀-ۿ‌‍‎ȘșȚț‪-‮]$/

export function formatCitationItem(
  citationItem: CitationItem,
  words: CitationWords = ENGLISH_CITATION_WORDS,
): string {
  const { itemData } = citationItem
  // Typed loosely on purpose: a name with neither part leaves `undefined` here
  // exactly as in the original, which then falls back to the title, and the
  // text has to come out the same as the desktop's for a note to round-trip.
  let str: any = ''

  if (!itemData) {
    return ''
  }

  const authors = itemData.author
  if (authors) {
    const name = (author: { family?: string; literal?: string }) =>
      author.family || author.literal
    if (authors.length === 1) {
      str = name(authors[0]!)
    } else if (authors.length === 2) {
      str = `${name(authors[0]!)} ${words.and} ${name(authors[1]!)}`
    } else if (authors.length >= 3) {
      str = `${name(authors[0]!)} ${words.etAl}`
    }
  }

  if (!str && itemData.title) {
    str = `“${itemData.title}”`
  }

  const year = itemData.issued?.['date-parts']?.[0]?.[0]
  // `!=` as in the original, where a numeric 0 and the string '0000' both
  // mean no year.
  if (year && year != '0000') {
    str += ', ' + year
  }

  if (citationItem.locator) {
    let label: string
    if (citationItem.label) {
      label = citationItem.label
    } else if (/[-–,]/.test(citationItem.locator)) {
      label = 'pp.'
    } else {
      label = 'p.'
    }
    str += ', ' + label + ' ' + citationItem.locator
  }

  if (citationItem.prefix) {
    str =
      citationItem.prefix +
      (ENDSWITH_ROMANESQUE_REGEXP.test(citationItem.prefix) ? ' ' : '') +
      str
  }

  if (citationItem.suffix) {
    str += (STARTSWITH_ROMANESQUE_REGEXP.test(citationItem.suffix) ? ' ' : '') + citationItem.suffix
  }

  return str as string
}
