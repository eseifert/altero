/**
 * How Zotero reads a date somebody typed, for the `y m d` beside the field.
 *
 * A port of `Zotero.Date.strToDate` from `zotero/utilities` (`date.js`, at the
 * revision the desktop pins, 4051881), AGPL like altero, with its month names
 * in `dateFormats.json` beside this file. The desktop's item pane shows the
 * order it found -- `d m y` for `26.10.2026` in Germany, `m d y` in the United
 * States -- so that whoever typed a date can see how it will be cited before
 * it is. Showing anything other than what the desktop would show would be a
 * second opinion about the same field, so this follows it line for line,
 * including the two places where it guesses: a two-digit year, and which of
 * two small numbers is the month.
 *
 * Only reading: the stored value is what was typed, as it is on the desktop.
 */

import dateFormats from './dateFormats.json'

interface Months {
  short: string[]
  long: string[]
}

const FORMATS = dateFormats as Record<string, Months>

export interface ParsedDate {
  /** The parts found, in the order they were written: `ymd`, `dmy`, `my`. */
  order: string
  year?: string
  /** Zero-based, as JavaScript counts months. */
  month?: number
  day?: number
  /** Whatever was not a year, a month or a day: `Summer`, `circa`. */
  part?: string
}

interface Part {
  part: string
  before?: boolean | string
  after?: boolean | string
}

const SLASH =
  /^(.*?)\b([0-9]{1,4})(?:([-/.年])([0-9]{1,2}))?(?:([-/.月])([0-9]{1,4}))?((?:\b|[^0-9]).*?)$/
const YEAR =
  /^(.*?)\b((?:circa |around |about |c\.? ?)?[0-9]{1,4}(?: ?B\.? ?C\.?(?: ?E\.?)?| ?C\.? ?E\.?| ?A\.? ?D\.?)|[0-9]{3,4})\b(.*?)$/i
/* `date.daySuffixes` reads "st, nd, rd, th" in every one of Zotero's own
   catalogues, English or not. */
const DAY = /\b([0-9]{1,2})(?:st|nd|rd|th)?\b(.*)/i

/** Countries whose dates put the month first, as `strToDate` lists them. */
const MONTH_FIRST = new Set(['US', 'FM', 'PW', 'PH'])

/** Month names for ``locale``, with English after them, as `Zotero.Date.init` builds them. */
function monthsFor(locale: string): Months {
  let tag = locale
  const english = tag.startsWith('en')
  if (!FORMATS[tag]) tag = tag.slice(0, 2)
  if (!FORMATS[tag]) tag = `${tag}-${tag.toUpperCase()}`
  if (!FORMATS[tag]) {
    const same = Object.keys(FORMATS).find((key) => key.startsWith(tag.slice(0, 2)))
    if (same) tag = same
  }
  const found = FORMATS[tag]
  if (!found) return FORMATS['en-US']
  if (english) return found
  return {
    short: found.short.concat(FORMATS['en-US'].short),
    long: found.long.concat(FORMATS['en-US'].long),
  }
}

const monthPatterns = new Map<string, { names: string[]; pattern: RegExp }>()

function monthPattern(locale: string): { names: string[]; pattern: RegExp } {
  let found = monthPatterns.get(locale)
  if (!found) {
    const months = monthsFor(locale)
    const names = months.short
      .map((name) => name.toLowerCase())
      .concat(months.long.map((name) => name.toLowerCase()))
    const escaped = names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    const pattern = new RegExp(`(.*)(?:^|[^\\p{L}])(${escaped.join('|')})[^ ]*(?: (.*)$|$)`, 'iu')
    found = { names, pattern }
    monthPatterns.set(locale, found)
  }
  return found
}

function insertOrderPart(order: string, part: string, where: Part): string {
  if (!order) return part
  if (where.before === true) return part + order
  if (where.after === true) return order + part
  if (where.before) {
    if (!order.includes(where.before)) return order
    return order.replace(new RegExp(`(${where.before})`), `${part}$1`)
  }
  if (where.after) {
    if (!order.includes(where.after)) return order + part
    return order.replace(new RegExp(`(${where.after})`), `$1${part}`)
  }
  return order + part
}

/**
 * Read ``value`` as Zotero would, in ``locale`` (a BCP 47 tag such as `en-US`).
 *
 * @param today Only for tests: the date a two-digit year is read against.
 */
export function strToDate(value: string, locale = 'en-US', today = new Date()): ParsedDate {
  let date: ParsedDate = { order: '' }
  const string = value.replace(/[\xA0\r\n\s]+/g, ' ').trim()
  if (!string) return date

  const parts: Part[] = []
  const m = SLASH.exec(string)
  if (
    m &&
    (!m[5] || !m[3] || m[3] === m[5] || (m[3] === '年' && m[5] === '月')) &&
    ((m[2] && m[4] && m[6]) || (!m[1] && !m[7]))
  ) {
    let year: string | number | undefined
    let month: string | number | undefined
    let day: string | number | undefined
    if (m[2].length === 3 || m[2].length === 4 || m[3] === '年') {
      year = m[2]
      month = m[4]
      day = m[6]
      date.order += m[2] ? 'y' : ''
      date.order += m[4] ? 'm' : ''
      date.order += m[6] ? 'd' : ''
    } else if (m[2] && !m[4] && m[6]) {
      month = m[2]
      year = m[6]
      date.order += m[2] ? 'm' : ''
      date.order += m[6] ? 'y' : ''
    } else {
      const country = locale.slice(3) || 'US'
      if (MONTH_FIRST.has(country)) {
        month = m[2]
        day = m[4]
        date.order += m[2] ? 'm' : ''
        date.order += m[4] ? 'd' : ''
      } else {
        month = m[4]
        day = m[2]
        date.order += m[2] ? 'd' : ''
        date.order += m[4] ? 'm' : ''
      }
      year = m[6]
      if (m[6] !== undefined) date.order += 'y'
    }

    const longYear = year !== undefined && String(year).length > 2
    if (year) year = parseInt(String(year), 10)
    if (day) day = parseInt(String(day), 10)
    if (month) {
      month = parseInt(String(month), 10)
      if (month > 12) {
        const swap = day
        day = month
        month = swap
        date.order = date.order
          .replace('m', 'D')
          .replace('d', 'M')
          .replace('D', 'd')
          .replace('M', 'm')
      }
    }

    if ((!month || (month as number) <= 12) && (!day || (day as number) <= 31)) {
      if (year && (year as number) < 100 && !longYear) {
        const current = today.getFullYear()
        const twoDigit = current % 100
        const century = current - twoDigit
        year = (year as number) <= twoDigit ? century + (year as number) : century - 100 + (year as number)
      }
      if (year !== undefined && year !== '') date.year = String(year)
      if (month) date.month = (month as number) - 1
      if (day) date.day = day as number
      parts.push({ part: m[1], before: true }, { part: m[7] })
    } else {
      date = { order: '' }
      parts.push({ part: string })
    }
  } else {
    parts.push({ part: string })
  }

  if (!date.year) {
    for (let i = 0; i < parts.length; i++) {
      const found = YEAR.exec(parts[i].part)
      if (found) {
        date.year = found[2]
        date.order = insertOrderPart(date.order, 'y', parts[i])
        parts.splice(i, 1, { part: found[1], before: true }, { part: found[3] })
        break
      }
    }
  }

  if (date.month === undefined) {
    const { names, pattern } = monthPattern(locale)
    for (let i = 0; i < parts.length; i++) {
      const found = pattern.exec(parts[i].part)
      if (found) {
        // Modulo 12, because the list carries English after the locale's own.
        date.month = names.indexOf(found[2].toLowerCase()) % 12
        date.order = insertOrderPart(date.order, 'm', parts[i])
        parts.splice(i, 1, { part: found[1], before: 'm' }, { part: found[3] ?? '', after: 'm' })
        break
      }
    }
  }

  if (!date.day) {
    for (let i = 0; i < parts.length; i++) {
      const found = DAY.exec(parts[i].part)
      if (found) {
        const day = parseInt(found[1], 10)
        if (day <= 31) {
          date.day = day
          date.order = insertOrderPart(date.order, 'd', parts[i])
          let part: string
          if (found.index > 0) {
            part = parts[i].part.slice(0, found.index)
            if (found[2]) part += ` ${found[2]}`
          } else {
            part = found[2]
          }
          parts.splice(i, 1, { part })
          break
        }
      }
    }
  }

  const rest = parts
    .map((entry) => `${entry.part} `)
    .join('')
    .replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, '')
  if (rest) date.part = rest

  return date
}

/** The indicator the item pane draws beside a date: `y m d`, or nothing. */
export function dateOrder(value: string, locale = 'en-US'): string {
  return strToDate(value, locale).order.split('').join(' ')
}
