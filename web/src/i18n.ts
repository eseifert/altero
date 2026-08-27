import { createI18n } from 'vue-i18n'

import da from './locales/da'
import de from './locales/de'
import enGB from './locales/en-GB'
import enUS from './locales/en-US'
import es from './locales/es'
import fr from './locales/fr'
import it from './locales/it'
import ja from './locales/ja'
import nl from './locales/nl'
import pl from './locales/pl'
import ptBR from './locales/pt-BR'
import ptPT from './locales/pt-PT'
import ru from './locales/ru'
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
  pl,
  ru,
  ja,
  'zh-CN': zhCN,
  'zh-TW': zhTW,
}

export type Locale = keyof typeof MESSAGES

export const LOCALES = Object.keys(MESSAGES) as Locale[]

/**
 * Which branch of a plural message a number asks for, per language.
 *
 * English separates one from many and every catalogue followed, because that is
 * what German, French, Spanish, Portuguese, Danish, Dutch and Italian do too --
 * and Japanese and Chinese, which inflect nothing, write the one form twice
 * rather than pretend to a distinction. Polish and Russian have a third form
 * for the small counts, so "2 elementy" and "5 elementów" are different words:
 * their catalogues carry three branches and these rules choose between them. A
 * catalogue written with English's two would be wrong on every count from 2 to
 * 4, which is what `locales.node.spec.ts` now checks for.
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
  /* Ends in 1 but not 11; ends in 2-4 but not 12-14; everything else. */
  ru: (choice: number, branches: number) => {
    const tens = choice % 10
    const hundreds = choice % 100
    if (tens === 1 && hundreds !== 11) return 0
    if (tens >= 2 && tens <= 4 && !(hundreds >= 12 && hundreds <= 14)) {
      return Math.min(1, branches - 1)
    }
    return Math.min(2, branches - 1)
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
 * Where a bare `en`, `pt` or `zh` goes, following CLDR's likely subtags.
 *
 * The same answer the server gives in `services/locales.py`, and
 * `tests/test_locales.py` fails if the two tables disagree -- the browser has
 * to resolve a tag before it has asked the server anything, so both sides carry
 * it.
 */
export const DEFAULT_VARIANTS: Record<string, Locale> = {
  en: 'en-US',
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
