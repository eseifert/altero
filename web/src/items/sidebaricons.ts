/**
 * Icons for the rows of a sidebar — the library's, and settings' — and for the
 * handful of controls elsewhere that are a glyph and nothing else: the tools
 * over the item list, and the path a dialog shows.
 *
 * A building names a library, groups share the main navigation's figures,
 * a folder names a collection, and a bin the trash. As with the item type
 * icons, they are redrawn as single-weight line glyphs on the same 24-unit
 * grid rather than copied — Zotero's own assets carry the client's license.
 *
 * Settings has no counterpart in the client, so those glyphs are only drawn to
 * the same rules: one weight, one grid, no fill.
 *
 * `sidebarIcon` falls back to the folder, so a row this build has no glyph for
 * still lines up with the rest instead of jumping to the inline start.
 */

import { CONTROL_ICONS, loadIcons, type SvgIcon } from '@/icons'

export const SIDEBAR_ICONS: Record<string, SvgIcon> = {
  ...loadIcons(
    import.meta.glob<string>('../assets/icons/sidebar/*.svg', {
      query: '?raw',
      import: 'default',
      eager: true,
    }),
  ),
  group: CONTROL_ICONS.groups,
}

export const FALLBACK_SIDEBAR_ICON = 'collection'

export function sidebarIcon(name: string): SvgIcon {
  return SIDEBAR_ICONS[name] ?? SIDEBAR_ICONS[FALLBACK_SIDEBAR_ICON]
}
