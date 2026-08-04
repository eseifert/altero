import { createI18n } from 'vue-i18n'

import de from './locales/de'
import en from './locales/en'
import es from './locales/es'
import fr from './locales/fr'
import ja from './locales/ja'
import pt from './locales/pt'

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

export const MESSAGES = { en, de, fr, es, pt, ja }

export type Locale = keyof typeof MESSAGES

export const LOCALES = Object.keys(MESSAGES) as Locale[]

export const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: MESSAGES,
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
