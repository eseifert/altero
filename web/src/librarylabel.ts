import { i18n } from '@/i18n'

/**
 * What a library is called, wherever one is named.
 *
 * A personal library is "My Library" whatever the account is called, which is
 * Zotero's word for it in the client and in its web library: the row is the
 * library, not its owner. A group is called what the group is called.
 *
 * Here rather than in the component that first needed it, because the sidebar
 * is not the only place a library is named — the settings page lists them to
 * export and to restore over — and two implementations of "what is this
 * called" is exactly how one of them ends up saying something else. That is
 * what happened: the sidebar started saying "My Library" and Import and export
 * went on printing the account holder's own name.
 *
 * Translated through the global instance rather than `useI18n`, so a plain
 * function can be called from anywhere and not only from inside a component.
 */
export interface NamedLibrary {
  type: string
  name: string
  ownerId: number
}

export function libraryLabel(entry: NamedLibrary): string {
  const { t } = i18n.global
  if (entry.type === 'user') return t('My Library')
  return entry.name || t('Group {id}', { id: entry.ownerId })
}
