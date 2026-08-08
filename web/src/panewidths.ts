/**
 * How wide the library's outer columns are, remembered between visits.
 *
 * Neither of them has a right answer. The sidebar holds a tree, and a tree is
 * as wide as whoever built it made it: "Reading" fits anywhere, "Cetacean
 * acoustics, 1990–2004" does not fit in anything a fixed default could pick.
 * The detail pane holds whatever the item is — three fields and a date for a
 * book, six hundred words of abstract for an article — and which of it and the
 * item list deserves the room is the reader's judgement, not ours.
 *
 * Stored per device rather than on the account, as the theme is: they are
 * properties of the window being read in, and the same person on a phone and on
 * a wide monitor does not want one answer for both.
 */

/** Where each chosen width is kept. */
export const SIDEBAR_STORAGE_KEY = 'altero.sidebar-width'
export const DETAIL_STORAGE_KEY = 'altero.detail-width'

/**
 * Widths in CSS pixels.
 *
 * The default is wider than the 14rem the column used to be capped at, which
 * was narrow enough that a collection two levels down had a dozen characters
 * to name itself in. The floor is the point below which the twisty, the icon
 * and an ellipsis are all that is left; the ceiling stops a drag from taking
 * the whole window and leaving no item list to drop anything on.
 */
export const SIDEBAR_DEFAULT = 288
export const SIDEBAR_MIN = 176
export const SIDEBAR_MAX = 560

/*
 * The detail pane. Its default is the even split the layout used to impose,
 * measured against a common enough window rather than left to `1fr`: an
 * abstract is prose, and prose in a column narrower than about thirty
 * characters is a ribbon nobody reads. The ceiling leaves the item list room
 * to still be a list.
 */
export const DETAIL_DEFAULT = 420
export const DETAIL_MIN = 260
export const DETAIL_MAX = 720

/** One pane's range, as the splitter that sizes it needs it. */
export interface PaneWidth {
  key: string
  min: number
  max: number
  preferred: number
}

export const SIDEBAR: PaneWidth = {
  key: SIDEBAR_STORAGE_KEY,
  min: SIDEBAR_MIN,
  max: SIDEBAR_MAX,
  preferred: SIDEBAR_DEFAULT,
}

export const DETAIL: PaneWidth = {
  key: DETAIL_STORAGE_KEY,
  min: DETAIL_MIN,
  max: DETAIL_MAX,
  preferred: DETAIL_DEFAULT,
}

/** ``width`` brought inside the range ``pane`` may take. */
export function clampWidth(pane: PaneWidth, width: number): number {
  return Math.min(pane.max, Math.max(pane.min, Math.round(width)))
}

/**
 * The stored width of ``pane``, or its default.
 *
 * Anything unreadable is the default rather than an error: this is a
 * convenience, and a corrupted entry -- or one written by a later version that
 * measured in something else -- must not stop the library from being drawn.
 */
export function readWidth(pane: PaneWidth): number {
  const stored = Number(localStorage.getItem(pane.key))
  return Number.isFinite(stored) && stored > 0 ? clampWidth(pane, stored) : pane.preferred
}

/** Remember ``width`` for the next visit. */
export function storeWidth(pane: PaneWidth, width: number): void {
  localStorage.setItem(pane.key, String(clampWidth(pane, width)))
}
