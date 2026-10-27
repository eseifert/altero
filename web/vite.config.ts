import { createHash } from 'node:crypto'
import { fileURLToPath, URL } from 'node:url'
import { brotliCompressSync, constants as zlibConstants, gzipSync } from 'node:zlib'

import vue from '@vitejs/plugin-vue'
import type { AtRule, Plugin as PostcssPlugin } from 'postcss'
import type { Plugin as VitePlugin } from 'vite'
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

/** What is worth compressing: text. Fonts and images are compressed already. */
const COMPRESSIBLE = /\.(js|css|svg|json|txt)$/

/**
 * Write a Brotli and a gzip copy beside every compressible asset.
 *
 * The server sends whichever the browser accepts (`api/spa.py`), so the
 * interface arrives compressed without compressing anything per request -- and
 * without compressing the API's responses or `/web`'s JSON, which a global
 * middleware would also have done. Brotli at its slowest setting, which costs
 * nothing at runtime since it happens once, here.
 *
 * The hook runs last: Vite's own `generateBundle` still rewrites the chunks,
 * filling in each dynamic import's `__VITE_PRELOAD__` marker, and a copy taken
 * before that fails in every browser that is sent it.
 */
export function precompress(): VitePlugin {
  return {
    name: 'altero-precompress',
    apply: 'build',
    generateBundle: {
      order: 'post',
      handler(_options, bundle) {
        for (const [fileName, output] of Object.entries(bundle)) {
          if (!COMPRESSIBLE.test(fileName)) continue
          const source = Buffer.from(output.type === 'chunk' ? output.code : output.source)
          if (source.length < 1024) continue
          this.emitFile({
            type: 'asset',
            fileName: `${fileName}.br`,
            source: brotliCompressSync(source, {
              params: { [zlibConstants.BROTLI_PARAM_QUALITY]: zlibConstants.BROTLI_MAX_QUALITY },
            }),
          })
          this.emitFile({
            type: 'asset',
            fileName: `${fileName}.gz`,
            source: gzipSync(source, { level: 9 }),
          })
        }
      },
    },
  }
}

/** The placeholder in the service worker that becomes the build's id. */
const BUILD_PLACEHOLDER = '__ALTERO_BUILD__'

/**
 * Write the service worker to `/app/sw.js`, stamped with an id of this build.
 *
 * A worker is replaced only when its script's bytes change, and its own code
 * changes rarely; what changes with every deploy is the set of fingerprinted
 * files. So the id is a digest of their names, and any build that changes a
 * single asset is a new worker, which then offers itself to open pages.
 */
export function serviceWorker(): VitePlugin {
  return {
    name: 'altero-service-worker',
    apply: 'build',
    generateBundle(_options, bundle) {
      const names = Object.keys(bundle)
        .filter((name) => name.startsWith('assets/'))
        .sort()
      const build = createHash('sha256').update(names.join('\n')).digest('hex').slice(0, 16)
      const worker = bundle['sw.js']
      if (!worker || worker.type !== 'chunk') throw new Error('The service worker was not built')
      if (worker.imports.length) throw new Error('The service worker must not import a shared chunk')
      worker.code = worker.code.replaceAll(BUILD_PLACEHOLDER, JSON.stringify(build))
    },
  }
}

export default defineConfig({
  plugins: [vue(), serviceWorker(), precompress()],
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
  // vue-i18n's compile-time flags: the Composition API only, and no devtools
  // hooks in a production build. Left undefined they are kept, and warned about.
  define: {
    __VUE_I18N_FULL_INSTALL__: true,
    __VUE_I18N_LEGACY_API__: false,
    __INTLIFY_PROD_DEVTOOLS__: false,
  },
  build: {
    outDir: fileURLToPath(new URL('../src/altero/web/static', import.meta.url)),
    emptyOutDir: true,
    /*
     * The oldest browser this interface is meant to work in.
     *
     * An iPhone SE that stopped at iOS 14.6 is a phone somebody still reads
     * on, and Vite's own default target assumes a browser three years newer:
     * the bundle would parse there and then fail on syntax Safari 14 does not
     * know. What this cannot do is polyfill *methods* -- `Array.prototype.at`
     * and the rest are avoided in the source instead -- or add a `<dialog>`,
     * which `modal.ts` answers for.
     */
    target: ['es2020', 'safari14', 'chrome87', 'firefox78', 'edge88'],
    // The favicons stay files rather than being inlined at their 750 bytes: a
    // tab icon is a URL the browser fetches, and index.html has to be able to
    // name one. Everything else, the header logos included, keeps the default
    // threshold and travels in the bundle.
    assetsInlineLimit: (file: string) =>
      /favicon-(light|dark)\.svg$/.test(file) ? false : undefined,
    rollupOptions: {
      // The service worker is an entry of its own, written unhashed: a
      // worker's URL is its identity, and a renamed one is a second worker.
      input: {
        index: fileURLToPath(new URL('./index.html', import.meta.url)),
        sw: fileURLToPath(new URL('./src/serviceworker/sw.ts', import.meta.url)),
      },
      output: {
        entryFileNames: (chunk) => (chunk.name === 'sw' ? 'sw.js' : 'assets/[name]-[hash].js'),
      },
    },
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
