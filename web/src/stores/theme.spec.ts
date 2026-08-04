import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ICONS, THEME_STORAGE_KEY, useThemeStore } from './theme'

/** Stand in for the OS setting, which jsdom does not model. */
function systemPrefersDark(dark: boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: dark && query.includes('dark'),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

describe('the theme store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    document.querySelectorAll('link[rel~="icon"]').forEach((link) => link.remove())
    systemPrefersDark(false)
  })

  /** The one icon link on the page, which is what a browser will show. */
  function icon(): HTMLLinkElement | null {
    const links = document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]')
    expect(links).toHaveLength(1)
    return links[0]
  }

  it('follows the system by default, because that is what most people expect', () => {
    const theme = useThemeStore()
    theme.initialise()

    expect(theme.preference).toBe('system')
  })

  it('resolves to light when the system asks for light', () => {
    systemPrefersDark(false)
    const theme = useThemeStore()
    theme.initialise()

    expect(theme.resolved).toBe('light')
  })

  it('resolves to dark when the system asks for dark', () => {
    systemPrefersDark(true)
    const theme = useThemeStore()
    theme.initialise()

    expect(theme.resolved).toBe('dark')
  })

  it('lets an explicit choice override the system', () => {
    systemPrefersDark(true)
    const theme = useThemeStore()
    theme.initialise()

    theme.setPreference('light')

    expect(theme.resolved).toBe('light')
  })

  it('stamps the resolved theme on the document so the tokens can switch', () => {
    const theme = useThemeStore()
    theme.initialise()

    theme.setPreference('dark')

    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('gives the tab the mark for the theme on screen', () => {
    systemPrefersDark(true)
    const theme = useThemeStore()

    theme.initialise()

    expect(icon()?.getAttribute('href')).toBe(ICONS.dark)
  })

  it('changes the tab icon with the theme, not only the page', () => {
    const theme = useThemeStore()
    theme.initialise()
    expect(icon()?.getAttribute('href')).toBe(ICONS.light)

    theme.setPreference('dark')

    expect(icon()?.getAttribute('href')).toBe(ICONS.dark)
  })

  it('leaves one icon behind, whichever the page was served with', () => {
    /* index.html carries a light mark for the moment before this runs. A
       browser that takes the last icon it is given would keep showing it. */
    for (const href of ['/light.svg', '/dark.svg']) {
      const link = document.createElement('link')
      link.rel = 'icon'
      link.href = href
      link.media = '(prefers-color-scheme: dark)'
      document.head.appendChild(link)
    }
    const theme = useThemeStore()

    theme.setPreference('dark')

    expect(icon()?.getAttribute('href')).toBe(ICONS.dark)
    expect(icon()?.hasAttribute('media')).toBe(false)
  })

  it('remembers an explicit choice across a reload', () => {
    const theme = useThemeStore()
    theme.initialise()
    theme.setPreference('dark')

    setActivePinia(createPinia())
    const reloaded = useThemeStore()
    reloaded.initialise()

    expect(reloaded.preference).toBe('dark')
    expect(reloaded.resolved).toBe('dark')
  })

  it('does not persist a choice of following the system as a fixed theme', () => {
    const theme = useThemeStore()
    theme.initialise()
    theme.setPreference('dark')

    theme.setPreference('system')

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
    expect(theme.resolved).toBe('light')
  })

  it('ignores a stored value that is not a theme', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'chartreuse')
    const theme = useThemeStore()

    theme.initialise()

    expect(theme.preference).toBe('system')
  })

  it('follows the system live while no explicit choice is set', () => {
    const listeners: Array<(event: MediaQueryListEvent) => void> = []
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: (_: string, handler: (event: MediaQueryListEvent) => void) =>
        listeners.push(handler),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia

    const theme = useThemeStore()
    theme.initialise()
    expect(theme.resolved).toBe('light')

    listeners.forEach((handler) => handler({ matches: true } as MediaQueryListEvent))

    expect(theme.resolved).toBe('dark')
  })

  it('stops following the system once a choice has been made', () => {
    const listeners: Array<(event: MediaQueryListEvent) => void> = []
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: (_: string, handler: (event: MediaQueryListEvent) => void) =>
        listeners.push(handler),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia

    const theme = useThemeStore()
    theme.initialise()
    theme.setPreference('light')

    listeners.forEach((handler) => handler({ matches: true } as MediaQueryListEvent))

    expect(theme.resolved).toBe('light')
  })
})
