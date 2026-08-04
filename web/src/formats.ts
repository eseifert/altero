import { useLocaleStore } from '@/stores/locale'

/**
 * Dates and times, written the way the reader writes them.
 *
 * Every timestamp the server sends is UTC, and every one of them is rendered
 * through `Intl` in the account's locale and time zone rather than the
 * browser's raw defaults — so `2019-04-03T22:30:00Z` is the third of April in
 * Berlin and the fourth in Tokyo, and neither reader has to know that.
 *
 * The formatters are cached: constructing an `Intl.DateTimeFormat` is
 * expensive enough to notice in a list, and a library view formats one per row.
 */

const cache = new Map<string, Intl.DateTimeFormat>()

function formatter(locale: string, zone: string, options: Intl.DateTimeFormatOptions) {
  const key = `${locale}|${zone}|${JSON.stringify(options)}`
  let found = cache.get(key)
  if (!found) {
    try {
      found = new Intl.DateTimeFormat(locale, { ...options, timeZone: zone })
    } catch {
      // An unknown locale or zone should not take the page down with it; the
      // browser's own defaults are a truthful fallback.
      found = new Intl.DateTimeFormat(undefined, options)
    }
    cache.set(key, found)
  }
  return found
}

function parse(value: string | Date | null | undefined): Date | null {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** A date on its own: `3 April 2019`, `3. April 2019`, `2019年4月3日`. */
export function formatDate(value: string | Date | null | undefined): string {
  const date = parse(value)
  if (!date) return ''
  const locale = useLocaleStore()
  return formatter(locale.formatting, locale.zone, { dateStyle: 'long' }).format(date)
}

/** A date with a time, for anything where the hour matters. */
export function formatDateTime(value: string | Date | null | undefined): string {
  const date = parse(value)
  if (!date) return ''
  const locale = useLocaleStore()
  return formatter(locale.formatting, locale.zone, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

/**
 * A date that names its own zone.
 *
 * Used where the reader may be somewhere other than the event was: a key last
 * used at 02:00 means something different if that was 02:00 somewhere else.
 */
export function formatDateTimeWithZone(value: string | Date | null | undefined): string {
  const date = parse(value)
  if (!date) return ''
  const locale = useLocaleStore()
  return formatter(locale.formatting, locale.zone, {
    dateStyle: 'medium',
    timeStyle: 'long',
  }).format(date)
}

/** Only what the discarded formatters cost. Used by tests. */
export function clearFormatterCache(): void {
  cache.clear()
}
