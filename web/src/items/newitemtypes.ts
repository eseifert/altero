/*
 * The types the *New Item* menu offers, the desktop's way
 * (`Zotero.ItemTypes.getPrimaryTypes`, `ZoteroPane.updateNewItemTypes`).
 *
 * Five primary types come first: the ones used last, made up to five from
 * the desktop's defaults. Every type follows, primary ones included. Web Page
 * is in neither, the desktop leaving it to the Connector, and neither are the
 * types that are not regular items.
 *
 * What was used last is kept in this browser alone, as the desktop keeps it in
 * its own preferences: it is a convenience of the person at this screen.
 */

export const DEFAULT_PRIMARY = ['book', 'bookSection', 'journalArticle', 'newspaperArticle', 'document']

const HIDDEN = new Set(['webpage', 'attachment', 'note', 'annotation'])

export const RECENT_TYPES_KEY = 'altero.newItemTypes'

/** The types used last, newest first, or none where storage is unavailable. */
export function recentTypes(): string[] {
  try {
    const stored = localStorage.getItem(RECENT_TYPES_KEY)
    const parsed: unknown = stored ? JSON.parse(stored) : []
    return Array.isArray(parsed) ? parsed.filter((entry): entry is string => typeof entry === 'string') : []
  } catch {
    return []
  }
}

/** Put ``itemType`` at the front of the recent list, keeping five. */
export function rememberType(itemType: string): void {
  const next = [itemType, ...recentTypes().filter((entry) => entry !== itemType)].slice(0, 5)
  try {
    localStorage.setItem(RECENT_TYPES_KEY, JSON.stringify(next))
  } catch {
    // Private browsing in Safari throws here; the menu keeps its defaults.
  }
}

/** The menu's two parts, each sorted by ``label``: the primary types and all of them. */
export function newItemMenu(
  available: string[],
  recent: string[],
  label: (itemType: string) => string,
  locale: string,
): { primary: string[]; all: string[] } {
  const offered = available.filter((name) => !HIDDEN.has(name))
  const known = new Set(offered)
  const primary = new Set(recent.filter((name) => known.has(name)).slice(0, DEFAULT_PRIMARY.length))
  for (const name of DEFAULT_PRIMARY) {
    if (primary.size >= DEFAULT_PRIMARY.length) break
    if (known.has(name)) primary.add(name)
  }
  const byLabel = (a: string, b: string) => label(a).localeCompare(label(b), locale)
  return { primary: [...primary].sort(byLabel), all: [...offered].sort(byLabel) }
}
