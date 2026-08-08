/**
 * How wide the library sidebar is, remembered between visits.
 *
 * The column holds a tree, and a tree is as wide as whoever built it made it:
 * "Reading" fits anywhere, "Cetacean acoustics, 1990–2004" does not fit in
 * anything a fixed default could reasonably pick. So the width is a decision
 * the reader takes once, with the pointer or the keyboard, and the browser
 * keeps it.
 *
 * Stored per device rather than on the account, as the theme is: it is a
 * property of the window being read in, and the same person on a phone and on
 * a wide monitor does not want one answer for both.
 */

/** Where the chosen width is kept. */
export const SIDEBAR_STORAGE_KEY = 'altero.sidebar-width'

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

/** ``width`` brought inside the range the sidebar may take. */
export function clampSidebarWidth(width: number): number {
  return Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(width)))
}

/**
 * The stored width, or the default.
 *
 * Anything unreadable is the default rather than an error: this is a
 * convenience, and a corrupted entry -- or one written by a later version that
 * measured in something else -- must not stop the library from being drawn.
 */
export function readSidebarWidth(): number {
  const stored = Number(localStorage.getItem(SIDEBAR_STORAGE_KEY))
  return Number.isFinite(stored) && stored > 0 ? clampSidebarWidth(stored) : SIDEBAR_DEFAULT
}

/** Remember ``width`` for the next visit. */
export function storeSidebarWidth(width: number): void {
  localStorage.setItem(SIDEBAR_STORAGE_KEY, String(clampSidebarWidth(width)))
}
