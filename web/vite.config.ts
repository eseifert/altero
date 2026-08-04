import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import type { AtRule, Plugin as PostcssPlugin } from 'postcss'
// From vitest/config rather than vite: it is the same function widened to
// accept the `test` block below, which vite's own types do not describe.
import { defineConfig } from 'vitest/config'

/**
 * Give every `@font-face` a `font-display: swap`.
 *
 * The Plex stylesheets are IBM's own and say nothing about display, which
 * leaves the default: a browser hides the text for as long as three seconds
 * while it fetches the face. The words matter more than which shapes they
 * arrive in, so they are painted in the fallback and swapped when Plex lands.
 * Done here rather than by copying 250 `@font-face` rules into this repo to
 * edit one line in each.
 */
export const swapFontDisplay: PostcssPlugin = {
  postcssPlugin: 'altero-font-display-swap',
  AtRule: {
    'font-face': (rule: AtRule) => {
      const declared = rule.some((node) => node.type === 'decl' && node.prop === 'font-display')
      if (!declared) rule.append({ prop: 'font-display', value: 'swap' })
    },
  },
}

export default defineConfig({
  plugins: [vue()],
  css: { postcss: { plugins: [swapFontDisplay] } },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // The built assets are served by the Python application under /app/, so
  // every generated URL has to be written relative to that prefix rather than
  // to the server root -- otherwise the SPA asks for /assets/... and collides
  // with the v3 API's own namespace.
  base: '/app/',
  build: {
    outDir: fileURLToPath(new URL('../src/altero/web/static', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` talks to a locally running altero, so the cookie the API
    // sets is same-origin from the browser's point of view.
    proxy: {
      '/web': 'http://127.0.0.1:8000',
      '/users': 'http://127.0.0.1:8000',
      '/groups': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.spec.ts'],
  },
})
