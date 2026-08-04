import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { clearFormatterCache, formatDate, formatDateTime } from '@/formats'
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
