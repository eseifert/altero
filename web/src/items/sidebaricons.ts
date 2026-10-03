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

import { loadIcons, type SvgIcon } from '@/icons'

export const SIDEBAR_ICONS = loadIcons(
  import.meta.glob<string>('../assets/icons/sidebar/*.svg', {
    query: '?raw',
    import: 'default',
    eager: true,
  }),
)

export const FALLBACK_SIDEBAR_ICON = 'collection'

export function sidebarIcon(name: string): SvgIcon {
  return SIDEBAR_ICONS[name] ?? SIDEBAR_ICONS[FALLBACK_SIDEBAR_ICON]
}
