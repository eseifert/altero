import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { clearFormatterCache, formatBytes, formatDate, formatDateTime } from '@/formats'
import { i18n, resolveLocale } from '@/i18n'

import { useLocaleStore } from './locale'

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
  i18n.global.locale.value = 'en'
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
    expect(resolveLocale(null, ['cy', 'is'])).toBe('en')
  })

  it('reads an underscore tag, which some browsers still send', () => {
    expect(resolveLocale(null, ['pt_BR'])).toBe('pt')
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

  it('uses the bare language when the browser is set to another one', () => {
    const store = browser(['en-US'], 'America/New_York')

    store.adopt({ language: 'de', timeZone: null })

    expect(store.formatting).toBe('de')
  })

  it('sets the document language, which assistive technology reads', () => {
    browser(['fr-FR'], 'Europe/Paris')

    expect(document.documentElement.lang).toBe('fr')
  })
})

describe('formatting dates', () => {
  it('writes a date the way the language does', () => {
    const store = browser(['en-GB'], 'UTC')
    store.adopt({ language: 'de', timeZone: 'Europe/Berlin' })

    expect(formatDate('2019-04-03T12:00:00Z')).toContain('2019')
    expect(formatDate('2019-04-03T12:00:00Z')).toContain('April')
  })

  it('puts an instant in the reader’s own zone', () => {
    /* 22:30 UTC is the third in Berlin and the fourth in Tokyo. The reader
       should not have to work that out. */
    const store = browser(['en-GB'], 'UTC')

    store.adopt({ language: 'en', timeZone: 'Europe/Berlin' })
    const berlin = formatDateTime('2019-04-03T22:30:00Z')

    store.adopt({ language: 'en', timeZone: 'Asia/Tokyo' })
    const tokyo = formatDateTime('2019-04-03T22:30:00Z')

    expect(berlin).toContain('3')
    expect(tokyo).toContain('4')
    expect(berlin).not.toBe(tokyo)
  })

  it('renders nothing for a missing or unreadable timestamp', () => {
    expect(formatDate(null)).toBe('')
    expect(formatDate('not a date')).toBe('')
  })
})

/**
 * A date's shape, in every language the interface offers.
 *
 * The words of the interface come from the catalogues; the shape of a date does
 * not. It is `Intl` over the CLDR data the browser already ships, which is why
 * a new language needs no date rules written for it here -- and why these tests
 * assert what CLDR produces rather than a table of our own. What they guard is
 * that a language reaches `Intl` at all: `formatting` handing over the wrong
 * tag would show every reader English dates and nothing would say so.
 */
describe('formatting a date in each language on offer', () => {
  it.each([
    ['en', 'April'],
    ['de', 'April'],
    ['fr', 'avril'],
    ['es', 'abril'],
    ['pt', 'abril'],
    ['it', 'aprile'],
    ['nl', 'april'],
    ['da', 'april'],
    ['pl', 'kwietnia'],
    ['ru', 'апреля'],
    ['ja', '4月'],
    ['zh', '4月'],
  ])('%s names the month in its own words', (language, month) => {
    const store = browser(['en-GB'], 'UTC')

    store.adopt({ language, timeZone: 'Europe/Berlin' })

    expect(formatDate('2019-04-04T12:00:00Z')).toContain(month)
  })

  it('separates the hour the way Danish does, with a full stop', () => {
    /* `00.30`, not `00:30`. Nothing in altero writes that rule down. */
    const store = browser(['en-GB'], 'UTC')

    store.adopt({ language: 'da', timeZone: 'Europe/Copenhagen' })

    expect(formatDateTime('2019-04-03T22:30:00Z')).toContain('00.30')
  })

  it('keeps a region the account never chose', () => {
    /* The Chinese catalogue is Simplified, so a reader in Taipei gets
       Simplified words -- but their dates stay Taiwanese, by the same rule
       that gives German words Austrian dates. */
    const store = browser(['zh-TW'], 'Asia/Taipei')

    store.adopt({ language: 'zh', timeZone: null })

    expect(store.active).toBe('zh')
    expect(store.formatting).toBe('zh-TW')
  })
})

describe('formatting a size', () => {
  it('writes the number the way the language writes numbers', () => {
    const store = browser(['en-GB'], 'UTC')

    store.adopt({ language: 'en', timeZone: null })
    expect(formatBytes(1_500_000)).toBe('1.5 MB')

    store.adopt({ language: 'pl', timeZone: null })
    expect(formatBytes(1_500_000)).toBe('1,5 MB')
  })

  it('takes the unit’s own name where the language has one', () => {
    /* Russian abbreviates megabyte in Cyrillic, and `Intl` knows that without
       a byte unit appearing in any catalogue. */
    const store = browser(['en-GB'], 'UTC')

    store.adopt({ language: 'ru', timeZone: null })

    expect(formatBytes(1_500_000)).toBe('1,5 МБ')
  })

  it('counts whole bytes below the first prefix', () => {
    browser(['en-GB'], 'UTC')

    expect(formatBytes(999)).toBe('999 byte')
  })
})
