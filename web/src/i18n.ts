import { createI18n } from 'vue-i18n'

import da from './locales/da'
import de from './locales/de'
import en from './locales/en'
import es from './locales/es'
import fr from './locales/fr'
import it from './locales/it'
import ja from './locales/ja'
import nl from './locales/nl'
import pl from './locales/pl'
import pt from './locales/pt'
import ru from './locales/ru'
import zh from './locales/zh'

/**
 * The interface's languages.
 *
 * Messages are keyed by their English text rather than by an invented
 * identifier. Two reasons: a template still reads as the sentence it renders,
 * and a key with no translation falls back to the key -- which is the English
 * sentence, not `settings.profile.heading`.
 *
 * `locales/en.ts` maps each key to itself. It is loaded rather than left
 * implicit because a message has to exist to be *compiled*: falling back to the
 * key gives the sentence but not its placeholders, so `{count}` would reach the
 * screen as four characters.
 *
 * Which language is used is decided in `resolveLocale`: the account's setting
 * first, then what the browser asks for, then English.
 */

export const MESSAGES = { en, de, fr, es, pt, it, nl, da, pl, ru, ja, zh }

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
  locale: 'en',
  fallbackLocale: 'en',
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
 * Return the language to use, given the account's setting.
 *
 * `null` from the account means "follow the browser", so the browser's ordered
 * list is consulted and the first language with a catalogue wins. A regional
 * tag counts for its language: `de-AT` is German here, while the region goes on
 * mattering for dates, which are formatted from the browser's own tag.
 */
export function resolveLocale(preference: string | null, browser: readonly string[]): Locale {
  const candidates = [preference, ...browser].filter((tag): tag is string => Boolean(tag))

  for (const tag of candidates) {
    const language = tag.replace('_', '-').split('-')[0].toLowerCase()
    if (isLocale(language)) return language
  }
  return 'en'
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
