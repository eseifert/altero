import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import iconDark from '@/assets/favicon-dark.svg'
import iconLight from '@/assets/favicon-light.svg'

/** What the user asked for, as opposed to what is on screen. */
export type ThemePreference = 'system' | 'light' | 'dark'

/** What is actually on screen. */
export type ResolvedTheme = 'light' | 'dark'

/**
 * The tab icon, per theme.
 *
 * The initial alone rather than the wordmark the header carries: a tab is
 * sixteen pixels square, and a mark two and a half times wider than it is tall
 * arrives there as a smear.
 */
export const ICONS: Record<ResolvedTheme, string> = { light: iconLight, dark: iconDark }

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
    paintIcon(resolved.value)
  }

  /**
   * Point the tab icon at the mark for the theme in force.
   *
   * The two logos are separate files rather than one drawn in `currentColor`,
   * so the icon has to be swapped rather than recoloured. It is done here, in
   * the same breath as the attribute, because a tab that says light while the
   * page is dark is the sort of thing nobody notices until it looks broken.
   * `media` on the link would leave the choice to the operating system, which
   * is exactly what an explicit theme choice is meant to override -- and not
   * every browser reads it there.
   */
  function paintIcon(theme: ResolvedTheme): void {
    const links = document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]')
    const icon = links[0] ?? document.head.appendChild(document.createElement('link'))

    // Any others are what index.html offered before this ran; a browser that
    // takes the last one would otherwise keep showing it.
    for (const spare of [...links].slice(1)) spare.remove()

    icon.rel = 'icon'
    icon.type = 'image/svg+xml'
    icon.removeAttribute('media')
    icon.href = ICONS[theme]
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
