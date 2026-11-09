import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { clearFormatterCache, formatBytes, formatDate, formatDateTime } from '@/formats'
import { resolveLocale, setLocale } from '@/i18n'

import { useLocaleStore } from './locale'

vi.mock('@/i18n', async (original) => ({
  ...await original<typeof import('@/i18n')>(),
  setLocale: vi.fn().mockResolvedValue(undefined),
}))

/**
 * Pretend the browser is set up somewhere in particular.
 *
 * The languages are mocked because the store reads `navigator`; the zone is set
 * on the store afterwards, because mocking `Intl.DateTimeFormat` would also
 * break the formatting the tests are checking.
 */
function browser(languages: string[], timeZone: string) {
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages)
  vi.spyOn(navigator, 'language', 'get').mockReturnValue(languages[0] ?? 'en')
  const store = useLocaleStore()
  store.initialise()
  store.browserTimeZone = timeZone
  return store
}

beforeEach(() => {
  setActivePinia(createPinia())
  clearFormatterCache()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe('choosing the language', () => {
  it('follows the browser when the account has not chosen', () => {
    expect(resolveLocale(null, ['de-AT', 'en'])).toBe('de')
  })

  it('lets the account override the browser', () => {
    expect(resolveLocale('ja', ['de-AT', 'en'])).toBe('ja')
  })

  it('walks the browser list until it finds one it speaks', () => {
    /* A machine set to Welsh then French should get French, not English. */
    expect(resolveLocale(null, ['cy', 'fr-CA', 'en'])).toBe('fr')
  })

  it('falls back to English when it speaks none of them', () => {
    expect(resolveLocale(null, ['cy', 'kl'])).toBe('en-US')
  })

  it('reads an underscore tag, which some browsers still send', () => {
    expect(resolveLocale(null, ['pt_BR'])).toBe('pt-BR')
  })
})

describe('the locale store', () => {
  it('reports both settings as automatic before the account says otherwise', () => {
    const store = useLocaleStore()

    expect(store.languageIsAutomatic).toBe(true)
    expect(store.timeZoneIsAutomatic).toBe(true)
  })

  it('takes the account’s settings when it has them', () => {
    const store = browser(['en-GB'], 'Europe/London')

    store.adopt({ language: 'ja', timeZone: 'Asia/Tokyo' })

    expect(store.active).toBe('ja')
    expect(store.zone).toBe('Asia/Tokyo')
    expect(store.languageIsAutomatic).toBe(false)
  })

  it('keeps the browser’s region when it agrees about the language', () => {
    /* German words, Austrian dates: choosing a language should not move
       somebody's date format to another country. */
    const store = browser(['de-AT'], 'Europe/Vienna')

    store.adopt({ language: 'de', timeZone: null })

    expect(store.active).toBe('de')
    expect(store.formatting).toBe('de-AT')
  })

  it('uses the language’s own tag when the browser is set to another one', () => {
    const store = browser(['en-US'], 'America/New_York')

    store.adopt({ language: 'de', timeZone: null })

    expect(store.formatting).toBe('de')
  })

  it('keeps Shahmukhi dates when the browser asks for Gurmukhi', () => {
    const store = browser(['pa-Guru-PK'], 'Asia/Karachi')
    store.adopt({ language: 'pa-Arab', timeZone: null })

    expect(store.formatting).toBe('pa-Arab')
  })

  it('keeps a Punjabi browser region when its script agrees', () => {
    const store = browser(['pa-PK'], 'Asia/Karachi')
    store.adopt({ language: 'pa-Arab', timeZone: null })

    expect(store.formatting).toBe('pa-PK')
  })

  it('awaits the resolved locale when adopting account settings', async () => {
    const store = browser(['en-US'], 'UTC')
    await store.adopt({ language: 'de', timeZone: null })
    expect(setLocale).toHaveBeenLastCalledWith('de')
  })
})

describe('formatting dates', () => {
  it('passes the selected locale and zone to Intl and caches date formatters', () => {
    const store = browser(['de-AT'], 'UTC')
    store.adopt({ language: 'de', timeZone: 'Europe/Berlin' })
    const date = new Date('2019-04-03T22:30:00Z')
    const expected = new Intl.DateTimeFormat('de-AT', {
      dateStyle: 'long', timeZone: 'Europe/Berlin',
    }).format(date)
    const DateFormat = Intl.DateTimeFormat
    const constructor = vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(function (locale, options) {
      return new DateFormat(locale, options)
    })
    expect(formatDate(date)).toBe(expected)
    expect(formatDate(date)).toBe(expected)
    expect(constructor).toHaveBeenCalledOnce()
    expect(constructor).toHaveBeenCalledWith('de-AT', {
      dateStyle: 'long', timeZone: 'Europe/Berlin',
    })
    store.adopt({ language: 'de', timeZone: 'Asia/Tokyo' })
    formatDateTime(date)
    expect(constructor).toHaveBeenLastCalledWith('de-AT', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tokyo',
    })
  })

  it('renders nothing for a missing or unreadable timestamp', () => {
    expect(formatDate(null)).toBe('')
    expect(formatDate('not a date')).toBe('')
  })
})

describe('regional formatting preferences', () => {
  it('keeps a region the account never chose', () => {
    /* An account set to Simplified Chinese on a machine in Taipei gets
       Simplified words -- that is what it asked for -- but its dates stay
       Taiwanese, by the same rule that gives German words Austrian dates. */
    const store = browser(['zh-TW'], 'Asia/Taipei')

    store.adopt({ language: 'zh-CN', timeZone: null })

    expect(store.active).toBe('zh-CN')
    expect(store.formatting).toBe('zh-TW')
  })

  it('follows the browser all the way to the variant when the account has not chosen', () => {
    /* Nothing stored, a machine in Taipei: Traditional words and Taiwanese
       dates. The catalogue is the one the region asks for, not the language's
       default. */
    const store = browser(['zh-TW'], 'Asia/Taipei')

    expect(store.active).toBe('zh-TW')
    expect(store.formatting).toBe('zh-TW')
  })
})

describe('formatting a size', () => {
  it.each([
    [null, 0, 'byte', 0], [-1, 0, 'byte', 0], [999.4, 999, 'byte', 0],
    [1000, 1, 'kilobyte', 1], [1_500_000, 1.5, 'megabyte', 1],
    [1e30, 1e15, 'petabyte', 1],
  ])('formats %s bytes using the selected locale and decimal unit', (bytes, amount, unit, digits) => {
    const store = browser(['de-AT'], 'UTC')
    store.adopt({ language: 'de', timeZone: null })
    const NumberFormat = Intl.NumberFormat
    const constructor = vi.spyOn(Intl, 'NumberFormat').mockImplementation(function (locale, options) {
      return new NumberFormat(locale, options)
    })
    const result = formatBytes(bytes)
    expect(constructor).toHaveBeenLastCalledWith('de-AT', {
      style: 'unit', unit, unitDisplay: 'short', maximumFractionDigits: digits,
    })
    expect(result).toBe(new Intl.NumberFormat('de-AT', {
      style: 'unit', unit, unitDisplay: 'short', maximumFractionDigits: digits,
    }).format(amount))
  })
})
