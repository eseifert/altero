import { afterEach, describe, expect, it } from 'vitest'

import { i18n, isLocale, LOCALES, matchLocale, PLURAL_RULES, resolveLocale } from './i18n'

/**
 * Counting, in the languages that count in more than two ways.
 *
 * English separates one from many, and so does every catalogue that followed
 * it. Polish and Russian have a third form for the small counts: "2 elementy"
 * against "5 elementów", "2 записи" against "5 записей". These tests are what
 * makes `pluralRules` in `i18n.ts` more than a claim -- take the rules out and
 * every count from 2 to 4 renders the wrong word.
 */

const ITEMS = '{count} item | {count} items'

/** Render the item count in one language, for one number. */
function items(locale: string, count: number): string {
  i18n.global.locale.value = locale as never
  return i18n.global.t(ITEMS, count)
}

afterEach(() => {
  i18n.global.locale.value = 'en-US'
})

describe('the languages on offer', () => {
  it('holds a catalogue for each', () => {
    expect(LOCALES).toEqual(
      expect.arrayContaining([
        'en-US',
        'en-GB',
        'de',
        'fr',
        'es',
        'pt-BR',
        'pt-PT',
        'it',
        'nl',
        'da',
        'pl',
        'ru',
        'ja',
        'zh-CN',
        'zh-TW',
      ]),
    )
  })

  it('recognises each as a locale and nothing else', () => {
    for (const locale of LOCALES) expect(isLocale(locale)).toBe(true)
    expect(isLocale('kl')).toBe(false)
    expect(isLocale('en')).toBe(false)
  })

  it('narrows a regional tag to the catalogue it has', () => {
    /* Most languages are carried once, so the region reaches dates and nothing
       else. */
    expect(resolveLocale(null, ['de-AT'])).toBe('de')
    expect(resolveLocale(null, ['fr-CA'])).toBe('fr')
  })

  it('keeps the region where the words depend on it', () => {
    expect(resolveLocale(null, ['zh-Hans-CN'])).toBe('zh-CN')
    expect(resolveLocale(null, ['zh-Hant'])).toBe('zh-TW')
    expect(resolveLocale(null, ['pt-BR'])).toBe('pt-BR')
    expect(resolveLocale(null, ['pt-PT'])).toBe('pt-PT')
    expect(resolveLocale(null, ['en-GB'])).toBe('en-GB')
  })

  it('sends a bare language where CLDR sends it', () => {
    expect(matchLocale('en')).toBe('en-US')
    expect(matchLocale('pt')).toBe('pt-BR')
    expect(matchLocale('zh')).toBe('zh-CN')
  })

  it('sends a territory with no catalogue to the one it reads', () => {
    /* Australia spells as Britain does, Hong Kong reads Traditional characters,
       and Angola writes European Portuguese. */
    expect(matchLocale('en-AU')).toBe('en-GB')
    expect(matchLocale('zh-HK')).toBe('zh-TW')
    expect(matchLocale('pt-AO')).toBe('pt-PT')
  })

  it('falls back to the default variant for a territory it has never heard of', () => {
    expect(matchLocale('en-CA')).toBe('en-US')
    expect(matchLocale('kl-GL')).toBeNull()
  })
})

describe('counting in a language with two forms', () => {
  it.each([
    ['en-US', 1, '1 item'],
    ['en-US', 2, '2 items'],
    ['en-GB', 2, '2 items'],
    ['de', 1, '1 Eintrag'],
    ['de', 5, '5 Einträge'],
  ])('%s renders %i', (locale, count, expected) => {
    expect(items(locale, count)).toBe(expected)
  })
})

describe('counting in Polish', () => {
  it.each([
    [1, '1 element'],
    [2, '2 elementy'],
    [4, '4 elementy'],
    [5, '5 elementów'],
    [0, '0 elementów'],
    [12, '12 elementów'],
    [14, '14 elementów'],
    [22, '22 elementy'],
    [25, '25 elementów'],
    [101, '101 elementów'],
    [102, '102 elementy'],
  ])('renders %i', (count, expected) => {
    expect(items('pl', count)).toBe(expected)
  })
})

describe('counting in Russian', () => {
  it.each([
    [1, '1 запись'],
    [2, '2 записи'],
    [4, '4 записи'],
    [5, '5 записей'],
    [0, '0 записей'],
    [11, '11 записей'],
    [14, '14 записей'],
    [21, '21 запись'],
    [22, '22 записи'],
    [25, '25 записей'],
    [111, '111 записей'],
  ])('renders %i', (count, expected) => {
    expect(items('ru', count)).toBe(expected)
  })
})

describe('a message with fewer branches than the language has forms', () => {
  /* An English message reached by fallback has two branches while these rules
     count three, so each one clamps to what it was handed rather than indexing
     past the end and rendering nothing at all. */
  it.each([
    ['pl', 5, 1],
    ['pl', 2, 1],
    ['ru', 5, 1],
    ['ru', 11, 1],
  ])('%s asks for no branch beyond the last', (locale, count, expected) => {
    expect(PLURAL_RULES[locale as 'pl' | 'ru'](count, 2)).toBe(expected)
  })

  it('still picks the singular for one', () => {
    expect(PLURAL_RULES.pl(1, 2)).toBe(0)
    expect(PLURAL_RULES.ru(21, 2)).toBe(0)
  })
})
