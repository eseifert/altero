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

/**
 * A number of bytes, in the reader's own numbering and units.
 *
 * Decimal steps rather than binary ones, and `Intl`'s own unit names, so a
 * German reader gets `1,5 MB` and a Japanese one `1.5 MB` without this file
 * knowing how either writes a number. Disk is sold and reported in decimal
 * everywhere an operator will compare this against.
 */
const BYTE_UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte', 'petabyte']

export function formatBytes(value: number | null | undefined): string {
  const bytes = Math.max(0, Math.round(value ?? 0))
  const locale = useLocaleStore()

  let step = 0
  let amount = bytes
  while (amount >= 1000 && step < BYTE_UNITS.length - 1) {
    amount /= 1000
    step += 1
  }

  try {
    return new Intl.NumberFormat(locale.formatting, {
      style: 'unit',
      unit: BYTE_UNITS[step],
      unitDisplay: 'short',
      // Whole bytes; one decimal once there is a prefix, because 1.5 GB and
      // 2 GB are different amounts of disk to buy and 1,502,341,904 is not an
      // amount anybody reads.
      maximumFractionDigits: step === 0 ? 0 : 1,
    }).format(amount)
  } catch {
    // An unknown locale must not take the page down; see `formatter` above.
    return `${Math.round(amount)} ${BYTE_UNITS[step]}`
  }
}

/** Only what the discarded formatters cost. Used by tests. */
export function clearFormatterCache(): void {
  cache.clear()
}
