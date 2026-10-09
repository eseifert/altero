import { createI18n } from 'vue-i18n'

import bn from './locales/bn'
import cs from './locales/cs'
import da from './locales/da'
import de from './locales/de'
import el from './locales/el'
import enGB from './locales/en-GB'
import enUS from './locales/en-US'
import es from './locales/es'
import fi from './locales/fi'
import fr from './locales/fr'
import hi from './locales/hi'
import hu from './locales/hu'
import id from './locales/id'
import it from './locales/it'
import ja from './locales/ja'
import ka from './locales/ka'
import ko from './locales/ko'
import lt from './locales/lt'
import nb from './locales/nb'
import nl from './locales/nl'
import pl from './locales/pl'
import ptBR from './locales/pt-BR'
import ptPT from './locales/pt-PT'
import ro from './locales/ro'
import ru from './locales/ru'
import sk from './locales/sk'
import sl from './locales/sl'
import sv from './locales/sv'
import ta from './locales/ta'
import tr from './locales/tr'
import uk from './locales/uk'
import vi from './locales/vi'
import zhCN from './locales/zh-CN'
import zhTW from './locales/zh-TW'

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

export const MESSAGES = {
  'en-US': enUS,
  'en-GB': enGB,
  de,
  fr,
  es,
  'pt-BR': ptBR,
  'pt-PT': ptPT,
  it,
  nl,
  da,
  nb,
  sv,
  fi,
  pl,
  cs,
  sk,
  sl,
  hu,
  ro,
  lt,
  ru,
  uk,
  el,
  ka,
  tr,
  hi,
  bn,
  ta,
  ja,
  ko,
  vi,
  id,
  'zh-CN': zhCN,
  'zh-TW': zhTW,
}

export type Locale = keyof typeof MESSAGES

export const LOCALES = Object.keys(MESSAGES) as Locale[]

/* Ends in 1 but not 11; ends in 2-4 but not 12-14; everything else. Russian
   and Ukrainian count alike. */
function eastSlavic(choice: number, branches: number): number {
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

/* Zero and one; everything else. Bengali and Hindi count nothing as they count
   one, where English counts it as many. */
function zeroAsOne(choice: number, branches: number): number {
  return choice <= 1 ? 0 : Math.min(1, branches - 1)
}

/**
 * Which branch of a plural message a number asks for, per language.
 *
 * English separates one from many and every catalogue followed, because that is
 * what German, French, Spanish, Portuguese, Danish, Norwegian, Swedish,
 * Finnish, Dutch, Italian, Greek and Tamil do too -- and Japanese, Korean,
 * Vietnamese, Indonesian, Bengali and Chinese, which inflect nothing, write the
 * one form twice rather than pretend to a distinction; Turkish, Hungarian and
 * Georgian, which count with the singular, do the same. Polish, Czech, Slovak,
 * Russian and Ukrainian have a third form for the small counts, so "2 elementy"
 * and "5 elementów" are different words: their catalogues carry three branches
 * and these rules choose between them. Slovenian has a dual as well, and so
 * four: "1 vnos", "2 vnosa", "3 vnosi", "5 vnosov". Romanian's third form is
 * for twenty and over, which take "de": "19 înregistrări" but
 * "20 de înregistrări". Lithuanian's is for nought, the tens and the teens:
 * "21 įrašas", "22 įrašai", "11 įrašų". Bengali and Hindi count zero with one
 * rather than with many. A catalogue written with English's two would be wrong
 * on every count from 2 to 4, which is what `locales.node.spec.ts` now checks
 * for.
 *
 * `branches` is how many the message actually has. Each rule clamps to it, so a
 * message reached by fallback -- English's two, under a rule that counts three
 * -- renders its last branch instead of nothing at all.
 */
export const PLURAL_RULES = {
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
  ru: eastSlavic,
  uk: eastSlavic,
  /* Ends in 1 and ends in 2-9, neither in 11-19; everything else. */
  lt: (choice: number, branches: number) => {
    const tens = choice % 10
    const hundreds = choice % 100
    const teen = hundreds >= 11 && hundreds <= 19
    if (tens === 1 && !teen) return 0
    if (tens >= 2 && !teen) return Math.min(1, branches - 1)
    return Math.min(2, branches - 1)
  },
  /* Exactly one; nought and anything ending in 1-19; everything else, which
     takes "de". */
  ro: (choice: number, branches: number) => {
    const hundreds = choice % 100
    if (choice === 1) return 0
    if (choice === 0 || (hundreds >= 1 && hundreds <= 19)) return Math.min(1, branches - 1)
    return Math.min(2, branches - 1)
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
  messages: MESSAGES,
  pluralRules: PLURAL_RULES,
  // A missing key renders as the key, which is the English text. That is a
  // usable result rather than an error, so it is not worth a console warning
  // per string on every render.
  missingWarn: false,
  fallbackWarn: false,
})

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as string[]).includes(value)
}

/**
 * Where a bare `en`, `pt` or `zh` goes, following CLDR's likely subtags, and
 * where `no` goes: Norwegian naming no written standard is read as Bokmål.
 *
 * The same answer the server gives in `services/locales.py`, and
 * `tests/test_locales.py` fails if the two tables disagree -- the browser has
 * to resolve a tag before it has asked the server anything, so both sides carry
 * it.
 */
export const DEFAULT_VARIANTS: Record<string, Locale> = {
  en: 'en-US',
  no: 'nb',
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
export const VARIANT_SUBTAGS: Record<string, Record<string, Locale>> = {
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
  no: {}, // One catalogue, Bokmål; see `DEFAULT_VARIANTS`.
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
  const subtags = tag.replace('_', '-').split('-')
  const language = subtags[0].toLowerCase()

  if (isLocale(language)) return language

  const variants = VARIANT_SUBTAGS[language]
  if (!variants) return null

  for (const subtag of subtags.slice(1)) {
    const found = variants[subtag.toLowerCase()]
    if (found) return found
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

/** Switch the interface, and tell assistive technology what it is reading. */
export function setLocale(locale: Locale): void {
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
}

/** Translate outside a component, where `useI18n` is not available. */
export function t(key: string, named?: Record<string, unknown>): string {
  return named ? i18n.global.t(key, named) : i18n.global.t(key)
}
