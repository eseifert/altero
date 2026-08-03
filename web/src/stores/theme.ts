import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/** What the user asked for, as opposed to what is on screen. */
export type ThemePreference = 'system' | 'light' | 'dark'

/** What is actually on screen. */
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'altero.theme'

const DARK_QUERY = '(prefers-color-scheme: dark)'

function isPreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark'
}

/**
 * The light/dark setting.
 *
 * Following the operating system is the default and the only state that is not
 * persisted: storing "system" as though it were a theme would freeze whatever
 * the system happened to be saying at the moment the user chose it, so the
 * absence of a stored value *is* the setting.
 */
export const useThemeStore = defineStore('theme', () => {
  const preference = ref<ThemePreference>('system')
  const systemPrefersDark = ref(false)

  const resolved = computed<ResolvedTheme>(() => {
    if (preference.value !== 'system') {
      return preference.value
    }
    return systemPrefersDark.value ? 'dark' : 'light'
  })

  function apply(): void {
    // The attribute is what the token sheet keys off. It is set for both
    // themes rather than only for dark, so that an explicit light choice wins
    // against a system that asks for dark.
    document.documentElement.dataset.theme = resolved.value
  }

  function setPreference(next: ThemePreference): void {
    preference.value = next
    if (next === 'system') {
      localStorage.removeItem(THEME_STORAGE_KEY)
    } else {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    }
    apply()
  }

  function initialise(): void {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    preference.value = isPreference(stored) && stored !== 'system' ? stored : 'system'

    const query = window.matchMedia(DARK_QUERY)
    systemPrefersDark.value = query.matches
    // Kept live: someone whose desktop switches at sunset should see this
    // switch with it, without reloading.
    query.addEventListener('change', (event: MediaQueryListEvent) => {
      systemPrefersDark.value = event.matches
      apply()
    })

    apply()
  }

  return { preference, resolved, setPreference, initialise }
})
