/**
 * Display names for item types, fields and creator types.
 *
 * Taken from the server's copy of the Zotero schema rather than restated here:
 * the schema already carries every name in 48 locales, and a hand-kept list
 * would drift from it the first time a field was added.
 *
 * Until that request finishes -- and for a field the schema does not name --
 * the camel case is split into words, so a label is always something readable
 * rather than a blank or a raw identifier.
 */

import { request } from '@/api/client'

interface DisplayNames {
  itemTypes: Record<string, string>
  fields: Record<string, string>
  creatorTypes: Record<string, string>
}

const names: DisplayNames = { itemTypes: {}, fields: {}, creatorTypes: {} }

let pending: Promise<void> | null = null

/** Split `publicationTitle` into `Publication Title`. */
export function humanize(name: string): string {
  const words = name
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** Load the display names once per page load; repeat calls await the first. */
export function loadLabels(locale?: string): Promise<void> {
  if (pending) return pending

  const query = locale ? `?locale=${encodeURIComponent(locale)}` : ''
  pending = request<DisplayNames>(`/web/schema${query}`)
    .then((payload) => {
      names.itemTypes = payload.itemTypes ?? {}
      names.fields = payload.fields ?? {}
      names.creatorTypes = payload.creatorTypes ?? {}
    })
    .catch(() => {
      // Labels are a nicety. The library still reads without them, and letting
      // this reject would take the whole view down with it.
      pending = null
    })

  return pending
}

export function fieldLabel(name: string): string {
  return names.fields[name] ?? names.creatorTypes[name] ?? humanize(name)
}

export function itemTypeLabel(name: string): string {
  return names.itemTypes[name] ?? humanize(name)
}

/** Discard what has been loaded. Used by tests, and by nothing else. */
export function resetLabels(): void {
  names.itemTypes = {}
  names.fields = {}
  names.creatorTypes = {}
  pending = null
}
