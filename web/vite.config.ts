import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
// From vitest/config rather than vite: it is the same function widened to
// accept the `test` block below, which vite's own types do not describe.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
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
