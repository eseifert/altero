import { createI18n } from 'vue-i18n'

import enUS from './locales/en-US'

/**
 * The interface's languages.
 *
 * Messages are keyed by their English text rather than by an invented
 * identifier. Two reasons: a template still reads as the sentence it renders,
 * and a key with no translation falls back to the key -- which is the English
 * sentence, not `settings.profile.heading`.
 *
 * `locales/en-US.ts` maps each key to itself. It is loaded rather than left
 * implicit because a message has to exist to be *compiled*: falling back to the
 * key gives the sentence but not its placeholders, so `{count}` would reach the
 * screen as four characters.
 *
 * Three languages are carried twice, because in those the territory changes the
 * words and not only the shape of a date: British and American English,
 * Brazilian and European Portuguese, Simplified and Traditional Chinese. They
 * are the same three Zotero splits. Everywhere else a region reaches dates
 * alone, and `de-AT` is German here.
 *
 * Which language is used is decided in `resolveLocale`: the account's setting
 * first, then what the browser asks for, then American English.
 */

export const LOCALES = [
  'en-US',
  'en-GB',
  'de',
  'fr',
  'br',
  'es',
  'pt-BR',
  'pt-PT',
  'ca',
  'eu',
  'gl',
  'it',
  'nl',
  'af',
  'ar',
  'da',
  'nb',
  'nn',
  'sv',
  'is',
  'fi',
  'pl',
  'cs',
  'sk',
  'sl',
  'hr',
  'sr',
  'hu',
  'ro',
  'lt',
  'lv',
  'et',
  'ru',
  'uk',
  'bg',
  'el',
  'ka',
  'mn',
  'tr',
  'ur',
  'pa-Arab',
  'hi',
  'bn',
  'ta',
  'ml',
  'ja',
  'ko',
  'th',
  'km',
  'vi',
  'id',
  'tl',
  'zh-CN',
  'zh-TW',
] as const

export type Locale = (typeof LOCALES)[number]

/**
 * Every catalogue but the American English one, each fetched when it is first
 * needed rather than shipped with the page: together they were nineteen
 * twentieths of the entry script, for a reader who reads one of them.
 */
const CATALOGUES = import.meta.glob<Record<string, string>>(
  ['./locales/*.ts', '!./locales/*.spec.ts', '!./locales/en-US.ts'],
  { import: 'default' },
)

const loaded = new Set<Locale>(['en-US'])

/* Ends in 1 but not 11; ends in 2-4 but not 12-14; everything else. Russian,
   Ukrainian, Croatian and Serbian count alike. */
function byLastDigits(choice: number, branches: number): number {
  const tens = choice % 10
  const hundreds = choice % 100
  if (tens === 1 && hundreds !== 11) return 0
  if (tens >= 2 && tens <= 4 && !(hundreds >= 12 && hundreds <= 14)) {
    return Math.min(1, branches - 1)
  }
  return Math.min(2, branches - 1)
}

/* Exactly one; exactly two to four; everything else. Czech and Slovak count
   alike, and unlike Polish neither goes back to the second form at 22. */
function czechSlovak(choice: number, branches: number): number {
  if (choice === 1) return 0
  if (choice >= 2 && choice <= 4) return Math.min(1, branches - 1)
  return Math.min(2, branches - 1)
}

/* Ends in 1 and ends in 2-9, neither in 11-19; everything else, which is
   nought, the tens and the teens. Lithuanian and Latvian count alike, CLDR's
   Latvian "zero" being Lithuanian's "many". */
function baltic(choice: number, branches: number): number {
  const tens = choice % 10
  const hundreds = choice % 100
  const teen = hundreds >= 11 && hundreds <= 19
  if (tens === 1 && !teen) return 0
  if (tens >= 2 && !teen) return Math.min(1, branches - 1)
  return Math.min(2, branches - 1)
}

/* Zero and one; everything else. Bengali and Hindi count nothing as they count
   one, where English counts it as many. */
function zeroAsOne(choice: number, branches: number): number {
  return choice <= 1 ? 0 : Math.min(1, branches - 1)
}

/** CLDR cardinal categories in the order used by a catalogue. Intl handles
 * fractions and negative counts as well as whole numbers. */
function byCategory(locale: string, categories: Intl.LDMLPluralRule[]) {
  const rules = new Intl.PluralRules(locale)
  return (choice: number, branches: number): number =>
    Math.min(categories.indexOf(rules.select(choice)), branches - 1)
}

/**
 * Which branch of a plural message a number asks for, per language.
 *
 * English separates one from many and every catalogue followed, because that is
 * what German, French, Spanish, Portuguese, Danish, Norwegian, Swedish,
 * Finnish, Estonian, Dutch, Afrikaans, Catalan, Galician, Bulgarian, Italian,
 * Greek, Tamil, Malayalam and Tagalog do too -- and Japanese, Korean, Thai,
 * Khmer, Vietnamese, Indonesian, Bengali and Chinese, which inflect nothing,
 * write the one form twice rather than pretend to a distinction; Turkish,
 * Hungarian, Georgian, Basque and Mongolian, which count with the singular, do
 * the same. Polish, Czech, Slovak, Croatian, Serbian, Russian and Ukrainian
 * have a third form for the small counts, so "2 elementy" and "5 elementów" are
 * different words: their catalogues carry three branches and these rules choose
 * between them. Slovenian has a dual as well, and so four: "1 vnos", "2 vnosa",
 * "3 vnosi", "5 vnosov". Romanian's third form is for twenty and over, which
 * take "de": "19 înregistrări" but "20 de înregistrări". Breton has five, and
 * they are about the mutation of the noun rather than its number:
 * "1 pezh-stag", "2 bezh-stag", "3 fezh-stag", "1000000 a bezhioù-stag",
 * "5 pezh-stag". Lithuanian's and Latvian's are for nought, the tens and the
 * teens: "21 įrašas", "22 įrašai", "11 įrašų"; "21 vienums", "22 vienumi",
 * "11 vienumu". Icelandic has the two forms English has, but chooses by the
 * last digit: "21 færsla", "11 færslur". Bengali and Hindi count zero with one
 * rather than with many. A catalogue written with English's two would be wrong
 * on every count from 2 to 4, which is what `locales.node.spec.ts` now checks
 * for.
 *
 * `branches` is how many the message actually has. Each rule clamps to it, so a
 * message reached by fallback -- English's two, under a rule that counts three
 * -- renders its last branch instead of nothing at all.
 */
export const PLURAL_RULES = {
  // https://unicode.org/cldr/charts/49/supplemental/language_plural_rules.html
  ar: byCategory('ar', ['zero', 'one', 'two', 'few', 'many', 'other']),
  'he-IL': byCategory('he', ['one', 'two', 'other']),
  fa: byCategory('fa', ['one', 'other']),
  'pa-Arab': byCategory('pa', ['one', 'other']),
  /* Exactly one; 2-4 but not 12-14; everything else. */
  pl: (choice: number, branches: number) => {
    const tens = choice % 10
    const hundreds = choice % 100
    if (choice === 1) return 0
    if (tens >= 2 && tens <= 4 && !(hundreds >= 12 && hundreds <= 14)) {
      return Math.min(1, branches - 1)
    }
    return Math.min(2, branches - 1)
  },
  cs: czechSlovak,
  sk: czechSlovak,
  bn: zeroAsOne,
  hi: zeroAsOne,
  hr: byLastDigits,
  sr: byLastDigits,
  ru: byLastDigits,
  uk: byLastDigits,
  lt: baltic,
  lv: baltic,
  /* Ends in 1 but not 11; everything else. */
  is: (choice: number, branches: number) =>
    choice % 10 === 1 && choice % 100 !== 11 ? 0 : Math.min(1, branches - 1),
  /* Exactly one; nought and anything ending in 1-19; everything else, which
     takes "de". */
  ro: (choice: number, branches: number) => {
    const hundreds = choice % 100
    if (choice === 1) return 0
    if (choice === 0 || (hundreds >= 1 && hundreds <= 19)) return Math.min(1, branches - 1)
    return Math.min(2, branches - 1)
  },
  /* CLDR's five: ending in 1; in 2; in 3, 4 or 9 -- none of them in the teens,
     the seventies or the nineties; a whole number of millions; everything else. */
  br: (choice: number, branches: number) => {
    const tens = choice % 10
    const exempt = [1, 7, 9].includes(Math.floor((choice % 100) / 10))
    if (tens === 1 && !exempt) return 0
    if (tens === 2 && !exempt) return Math.min(1, branches - 1)
    if ([3, 4, 9].includes(tens) && !exempt) return Math.min(2, branches - 1)
    if (choice !== 0 && choice % 1000000 === 0) return Math.min(3, branches - 1)
    return Math.min(4, branches - 1)
  },
  /* By the last two digits: 1, 2, 3-4, everything else. */
  sl: (choice: number, branches: number) => {
    const hundreds = choice % 100
    if (hundreds === 1) return 0
    if (hundreds === 2) return Math.min(1, branches - 1)
    if (hundreds === 3 || hundreds === 4) return Math.min(2, branches - 1)
    return Math.min(3, branches - 1)
  },
}

export const i18n = createI18n({
  legacy: false,
  locale: 'en-US',
  fallbackLocale: 'en-US',
  // Typed as a map of catalogues rather than inferred from the one loaded up
  // front, which would admit only American English as a locale.
  messages: { 'en-US': enUS } as Record<string, Record<string, string>>,
  pluralRules: PLURAL_RULES,
  // A missing key renders as the key, which is the English text. That is a
  // usable result rather than an error, so it is not worth a console warning
  // per string on every render.
  missingWarn: false,
  fallbackWarn: false,
})

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value)
}

/**
 * Where a bare `en`, `pt` or `zh` goes, following CLDR's likely subtags, and
 * where `no` and `fil` go: Norwegian naming no written standard is read as
 * Bokmål, and Filipino, the standardised Tagalog, as Tagalog.
 *
 * The same answer the server gives in `services/locales.py`, and
 * `tests/test_locales.py` fails if the two tables disagree -- the browser has
 * to resolve a tag before it has asked the server anything, so both sides carry
 * it.
 */
export const DEFAULT_VARIANTS: Record<string, Locale | null> = {
  en: 'en-US',
  fil: 'tl',
  no: 'nb',
  // Bare Punjabi implies Gurmukhi; only Shahmukhi has a catalogue here.
  pa: null,
  pt: 'pt-BR',
  zh: 'zh-CN',
}

/**
 * The region and script subtags that pick a variant, lowercased.
 *
 * A territory with no catalogue of its own is sent to the one it reads: Ireland
 * and Australia spell as Britain does, Angola and Mozambique write European
 * Portuguese, and Hong Kong and Macau read Traditional characters. Anything not
 * named here falls through to `DEFAULT_VARIANTS`.
 */
export const VARIANT_SUBTAGS: Record<string, Record<string, Locale | null>> = {
  en: {
    us: 'en-US',
    au: 'en-GB',
    gb: 'en-GB',
    ie: 'en-GB',
    in: 'en-GB',
    nz: 'en-GB',
    uk: 'en-GB',
    za: 'en-GB',
  },
  fil: {}, // One catalogue, Tagalog; see `DEFAULT_VARIANTS`.
  no: {}, // One catalogue, Bokmål; see `DEFAULT_VARIANTS`.
  pa: {
    arab: 'pa-Arab',
    guru: null, // An explicit script wins even with a Pakistani region.
    pk: 'pa-Arab',
  },
  pt: {
    br: 'pt-BR',
    ao: 'pt-PT',
    cv: 'pt-PT',
    gw: 'pt-PT',
    mz: 'pt-PT',
    pt: 'pt-PT',
    st: 'pt-PT',
    tl: 'pt-PT',
  },
  zh: {
    cn: 'zh-CN',
    hans: 'zh-CN',
    sg: 'zh-CN',
    hant: 'zh-TW',
    hk: 'zh-TW',
    mo: 'zh-TW',
    tw: 'zh-TW',
  },
}

/**
 * Return the catalogue a language tag asks for, or `null` for one we lack.
 *
 * A tag is narrowed to what there is a catalogue for. For most languages that
 * drops the region, `de-AT` being German; for the three written differently in
 * different places the region is kept and, where it names a territory with no
 * catalogue of its own, translated to the one that territory reads.
 */
export function matchLocale(tag: string): Locale | null {
  const subtags = tag.replaceAll('_', '-').split('-')
  const language = subtags[0].toLowerCase()

  if (isLocale(language)) return language

  const variants = VARIANT_SUBTAGS[language]
  if (!variants) return null

  for (const subtag of subtags.slice(1)) {
    if (Object.hasOwn(variants, subtag.toLowerCase())) return variants[subtag.toLowerCase()]
  }
  return DEFAULT_VARIANTS[language]
}

/**
 * Return the language to use, given the account's setting.
 *
 * `null` from the account means "follow the browser", so the browser's ordered
 * list is consulted and the first language with a catalogue wins.
 */
export function resolveLocale(preference: string | null, browser: readonly string[]): Locale {
  const candidates = [preference, ...browser].filter((tag): tag is string => Boolean(tag))

  for (const tag of candidates) {
    const matched = matchLocale(tag)
    if (matched) return matched
  }
  return 'en-US'
}

/** Fetch a catalogue, if it has not been already. */
export async function loadLocale(locale: Locale): Promise<void> {
  if (loaded.has(locale)) return
  const load = CATALOGUES[`./locales/${locale}.ts`]
  if (!load) return
  i18n.global.setLocaleMessage(locale, await load())
  loaded.add(locale)
}

let requested: Locale = 'en-US'

/**
 * Switch the interface, and tell assistive technology what it is reading.
 *
 * The catalogue is fetched first, so the words change once rather than to
 * English and back. A switch asked for while an earlier one is still fetching
 * wins: the earlier one finds it has been overtaken and leaves the language
 * alone.
 */
export async function setLocale(locale: Locale): Promise<void> {
  requested = locale
  await loadLocale(locale)
  if (requested !== locale) return
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
}

/** Translate outside a component, where `useI18n` is not available. */
export function t(key: string, named?: Record<string, unknown>): string {
  return named ? i18n.global.t(key, named) : i18n.global.t(key)
}
