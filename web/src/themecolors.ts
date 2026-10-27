/**
 * The colour of the browser's own chrome, per theme: the header bar's
 * `surface-container` (styles/tokens.css), so that an installed app's title
 * bar runs on into the page's. Read by the theme store, which keeps the
 * `theme-color` in step, and held to the manifest by `pwa.node.spec.ts`.
 */
export const CHROME_COLORS = { light: '#f2f5f4', dark: '#1d2020' } as const
