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

import { reactive } from 'vue'

import { request } from '@/api/client'

interface DisplayNames {
  itemTypes: Record<string, string>
  fields: Record<string, string>
  creatorTypes: Record<string, string>
}

/* Reactive, because the names always arrive after the first render. Anything
   that asked for a label before the request finished has to be told when the
   answer is in, or it keeps the split camel case for as long as it is shown. */
const names: DisplayNames = reactive({ itemTypes: {}, fields: {}, creatorTypes: {} })

/** The locale the names in hand, or the request in flight, were asked for. */
let wanted: string | null = null

let pending: Promise<void> | null = null

/** Split `publicationTitle` into `Publication Title`. */
export function humanize(name: string): string {
  const words = name
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * Load the display names for one locale; repeat calls for it await the first.
 *
 * A different locale is a different set of names, so it is fetched again: the
 * interface's language can change while it is open, and labels that stayed in
 * the language before it would be the only English left on a German page.
 */
export function loadLabels(locale?: string): Promise<void> {
  const asked = locale ?? ''
  if (pending && wanted === asked) return pending

  wanted = asked
  const query = locale ? `?locale=${encodeURIComponent(locale)}` : ''
  const inflight: Promise<void> = request<DisplayNames>(`/web/schema${query}`)
    .then((payload) => {
      // A later language may have overtaken this one. The newest request is
      // the one whose names belong on screen, whichever answers first.
      if (pending !== inflight) return
      names.itemTypes = payload.itemTypes ?? {}
      names.fields = payload.fields ?? {}
      names.creatorTypes = payload.creatorTypes ?? {}
    })
    .catch(() => {
      // Labels are a nicety. The library still reads without them, and letting
      // this reject would take the whole view down with it.
      if (pending === inflight) {
        pending = null
        wanted = null
      }
    })
  pending = inflight

  return inflight
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
  wanted = null
}
