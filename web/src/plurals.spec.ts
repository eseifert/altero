import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'

import { PLURAL_RULES } from './i18n'

// CLDR cardinal categories in catalogue order. Render through Vue I18n too:
// merely testing a selector would miss its built-in two/three-branch handling.
// One representative per custom algorithm, with boundaries that distinguish
// altero's rules. Aliases sharing an implementation need no duplicate examples.
const CASES: [string, string, [number, string][]][] = [
  ['pl', 'A | B | C', [[1, 'A'], [2, 'B'], [4, 'B'], [5, 'C'], [0, 'C'], [12, 'C'], [14, 'C'], [22, 'B'], [101, 'C']]],
  ['cs', 'A | B | C', [[1, 'A'], [2, 'B'], [4, 'B'], [0, 'C'], [5, 'C'], [22, 'C']]],
  ['ru', 'A | B | C', [[1, 'A'], [21, 'A'], [2, 'B'], [22, 'B'], [0, 'C'], [5, 'C'], [11, 'C'], [14, 'C']]],
  ['lt', 'A | B | C', [[1, 'A'], [21, 'A'], [2, 'B'], [9, 'B'], [22, 'B'], [0, 'C'], [10, 'C'], [11, 'C'], [19, 'C']]],
  ['bn', 'A | B', [[0, 'A'], [1, 'A'], [2, 'B']]],
  ['is', 'A | B', [[1, 'A'], [21, 'A'], [101, 'A'], [0, 'B'], [2, 'B'], [11, 'B'], [111, 'B']]],
  ['ro', 'A | B | C', [[1, 'A'], [0, 'B'], [2, 'B'], [19, 'B'], [101, 'B'], [119, 'B'], [20, 'C'], [21, 'C'], [100, 'C'], [120, 'C']]],
  ['sl', 'A | B | C | D', [[1, 'A'], [101, 'A'], [2, 'B'], [102, 'B'], [3, 'C'], [4, 'C'], [103, 'C'], [0, 'D'], [5, 'D'], [11, 'D']]],
  ['br', 'A | B | C | D | E', [[1, 'A'], [21, 'A'], [2, 'B'], [22, 'B'], [3, 'C'], [4, 'C'], [9, 'C'], [89, 'C'], [1000000, 'D'], [0, 'E'], [11, 'E'], [12, 'E'], [13, 'E'], [71, 'E'], [79, 'E'], [92, 'E'], [99, 'E']]],
  // Only integration examples for category-based selectors: Intl supplies CLDR.
  ['ar', 'A | B | C | D | E | F', [[0, 'A'], [1, 'B'], [2, 'C'], [3, 'D'], [11, 'E'], [100, 'F']]],
  ['he-IL', 'A | B | C', [[1, 'A'], [2, 'B'], [3, 'C']]],
  ['fa', 'A | B', [[0, 'A'], [2, 'B']]],
  ['pa-Arab', 'A | B', [[0, 'A'], [2, 'B']]],
]

describe.each(CASES)('%s cardinal plurals', (locale, message, examples) => {
  const translator = createI18n({
    legacy: false,
    locale,
    fallbackLocale: false,
    messages: { [locale]: { count: message } },
    pluralRules: PLURAL_RULES,
  })

  it('selects the expected branch through Vue I18n', () => {
    for (const [count, expected] of examples) {
      expect(translator.global.t('count', count), String(count)).toBe(expected)
    }
  })

  it('keeps shortened fallback messages within their available branches', () => {
    translator.global.setLocaleMessage(locale, { count: 'first | last' })
    for (const [count, expected] of examples) {
      expect(translator.global.t('count', count), String(count)).toBe(expected === 'A' ? 'first' : 'last')
    }
  })
})
