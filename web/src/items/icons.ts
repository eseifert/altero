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

import { loadIcons, type SvgIcon } from '@/icons'

export const ITEM_TYPE_ICONS = loadIcons(
  import.meta.glob<string>('../assets/icons/items/*.svg', {
    query: '?raw',
    import: 'default',
    eager: true,
  }),
)

/** The type used when the server names one this build does not know. */
export const FALLBACK_ITEM_TYPE = 'document'

export function iconFor(itemType: string): SvgIcon {
  return ITEM_TYPE_ICONS[itemType] ?? ITEM_TYPE_ICONS[FALLBACK_ITEM_TYPE]
}
