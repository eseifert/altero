import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { resolveLocale, setLocale, type Locale } from '@/i18n'

/**
 * Which language the interface is in, and which clock its dates are on.
 *
 * Both come from the account, and `null` there means "follow the browser" — so
 * this store holds the account's answer and works out what that resolves to
 * here, on this machine, now.
 *
 * The two are deliberately separate. The language decides the words; the
 * *formatting* locale decides the shape of a date, and it keeps the browser's
 * region whenever the browser agrees about the language: someone whose account
 * says German and whose machine says `de-AT` gets German words and Austrian
 * dates, and someone reading British English on an Australian machine keeps
 * Australian ones. Choosing a language should not silently move somebody's date
 * format to another country's.
 */
export const useLocaleStore = defineStore('locale', () => {
  /** The account's setting, or null for "follow the browser". */
  const language = ref<string | null>(null)
  const timeZone = ref<string | null>(null)

  /** What the browser asks for, read once. */
  const browserLanguages = ref<readonly string[]>([])
  const browserTimeZone = ref('UTC')

  const active = computed<Locale>(() => resolveLocale(language.value, browserLanguages.value))

  /**
   * The tag used for formatting: the browser's own when it names the language
   * in force, so its region survives; otherwise the language's own tag, which
   * for six of the catalogues already names a territory.
   *
   * Matched on the language and not on the whole tag, so a reader in Taipei
   * whose account says Simplified Chinese still gets Taiwanese dates -- the
   * same rule that gives German words Austrian dates, and the reason the schema
   * labels are asked for with `active` rather than with this.
   */
  const formatting = computed(() => {
    const language = active.value.split('-')[0]
    const preferred = browserLanguages.value.find(
      (tag) => tag.replace('_', '-').split('-')[0].toLowerCase() === language,
    )
    return preferred ?? active.value
  })

  const zone = computed(() => timeZone.value ?? browserTimeZone.value)

  /** Whether each setting is being deferred to the browser, for the settings screen. */
  const languageIsAutomatic = computed(() => language.value === null)
  const timeZoneIsAutomatic = computed(() => timeZone.value === null)

  function initialise(): void {
    browserLanguages.value = navigator.languages?.length
      ? [...navigator.languages]
      : [navigator.language]
    try {
      browserTimeZone.value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    } catch {
      // A browser that cannot say where it is gets UTC, which is at least a
      // zone rather than a guess at one.
      browserTimeZone.value = 'UTC'
    }
    apply()
  }

  /** Take the settings from the account, as the session reports them. */
  function adopt(preferences: { language: string | null; timeZone: string | null }): void {
    language.value = preferences.language
    timeZone.value = preferences.timeZone
    apply()
  }

  function apply(): void {
    setLocale(active.value)
  }

  return {
    language,
    timeZone,
    active,
    formatting,
    zone,
    languageIsAutomatic,
    timeZoneIsAutomatic,
    browserTimeZone,
    initialise,
    adopt,
  }
})
