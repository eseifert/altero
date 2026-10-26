/**
 * The browser end-to-end suite: the built interface, a real server, a real browser.
 *
 * What jsdom cannot tell: whether the build runs under the server's
 * Content-Security-Policy, whether a page is usable with a keyboard and a
 * screen reader (axe), and what a phone-sized viewport does to the layout.
 * `e2e/setup.ts` starts `altero serve` on a throwaway SQLite database and
 * seeds it through the v3 API, so the data is what a desktop would have synced.
 *
 * Run `npm run build` first: the server serves `src/altero/web/static`.
 */
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/setup.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? [['list'], ['json', { outputFile: 'test-results/results.json' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${process.env.ALTERO_E2E_PORT ?? '8766'}`,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
})
