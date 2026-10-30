import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'

import { PLURAL_RULES } from './i18n'

// CLDR cardinal categories in catalogue order. Render through Vue I18n too:
// merely testing a selector would miss its built-in two/three-branch handling.
const CASES: [string, string, [number, string][]][] = [
  ['ar', 'zero | one | two | few | many | other', [
    [0, 'zero'], [1, 'one'], [2, 'two'], [3, 'few'], [10, 'few'],
    [11, 'many'], [99, 'many'], [100, 'other'], [101, 'other'],
    [102, 'other'], [103, 'few'], [111, 'many'], [1.5, 'other'], [-3, 'few'],
  ]],
  ['he-IL', 'one | two | other', [
    [0, 'other'], [1, 'one'], [2, 'two'], [3, 'other'], [10, 'other'],
    [20, 'other'], [0.5, 'one'], [1.5, 'other'],
  ]],
  ['fa', 'one | other', [[0, 'one'], [0.5, 'one'], [1, 'one'], [2, 'other']]],
  ['pa-Arab', 'one | other', [[0, 'one'], [1, 'one'], [2, 'other']]],
]

describe.each(CASES)('%s cardinal plurals', (locale, message, examples) => {
  const translator = createI18n({
    legacy: false,
    locale,
    fallbackLocale: false,
    messages: { [locale]: { count: message } },
    pluralRules: PLURAL_RULES,
  })

  it.each(examples)('renders %s as %s', (count, expected) => {
    expect(translator.global.t('count', count)).toBe(expected)
  })

  it('keeps shortened fallback messages within their available branches', () => {
    translator.global.setLocaleMessage(locale, { count: 'first | last' })
    for (const [count] of examples) {
      expect(['first', 'last']).toContain(translator.global.t('count', count))
    }
  })
})
