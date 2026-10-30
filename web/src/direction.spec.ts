import { afterEach, describe, expect, it } from 'vitest'

import { i18n, setLocale, type Locale } from './i18n'

const prototype = Intl.Locale.prototype
const original = Object.getOwnPropertyDescriptor(prototype, 'getTextInfo')

function textInfo(value: unknown): void {
  Object.defineProperty(prototype, 'getTextInfo', { configurable: true, value })
}

afterEach(async () => {
  if (original) Object.defineProperty(prototype, 'getTextInfo', original)
  else Reflect.deleteProperty(prototype, 'getTextInfo')
  await setLocale('en-US')
})

const DIRECTIONS: [Locale, string][] = [
  ['ar', 'rtl'], ['fa', 'rtl'], ['he-IL', 'rtl'], ['ur', 'rtl'], ['pa-Arab', 'rtl'],
  ['en-US', 'ltr'], ['de', 'ltr'], ['ja', 'ltr'],
]

describe('document direction', () => {
  it.each(DIRECTIONS)('sets %s to %s with its language', async (locale, direction) => {
    await setLocale(locale)

    expect(document.documentElement.lang).toBe(locale)
    expect(document.documentElement.dir).toBe(direction)
    expect(i18n.global.locale.value).toBe(locale)
  })

  it.each(DIRECTIONS)('supports %s without getTextInfo', async (locale, direction) => {
    textInfo(undefined)
    await setLocale(locale)

    expect(document.documentElement.dir).toBe(direction)
  })

  it('uses the browser’s text information when available', async () => {
    let asked = ''
    textInfo(function (this: Intl.Locale) {
      asked = this.baseName
      return { direction: 'rtl' }
    })
    await setLocale('en-US')

    expect(asked).toBe('en-US')
    expect(document.documentElement.dir).toBe('rtl')
  })

  it('falls back when the browser has no direction for a locale', async () => {
    textInfo(() => ({ direction: undefined }))
    await setLocale('ar')

    expect(document.documentElement.dir).toBe('rtl')
  })

  it('keeps the previous direction until the catalogue is ready', async () => {
    await setLocale('en-US')
    const switching = setLocale('ar')

    expect(document.documentElement.lang).toBe('en-US')
    expect(document.documentElement.dir).toBe('ltr')
    await switching
    expect(document.documentElement.lang).toBe('ar')
    expect(document.documentElement.dir).toBe('rtl')
  })

  it('switches back from right to left to left to right', async () => {
    await setLocale('ar')
    await setLocale('de')

    expect(document.documentElement.lang).toBe('de')
    expect(document.documentElement.dir).toBe('ltr')
  })

  it.each([['ar', 'de', 'ltr'], ['de', 'he-IL', 'rtl']] as const)(
    'keeps the later direction when %s is overtaken by %s',
    async (earlier, later, direction) => {
      await Promise.all([setLocale(earlier), setLocale(later)])

      expect(document.documentElement.lang).toBe(later)
      expect(document.documentElement.dir).toBe(direction)
    },
  )
})
