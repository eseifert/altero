import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: 'e2e-registration',
  outputDir: 'registration-results',
  globalSetup: './e2e-registration/setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60000,
  reporter: [['list'], ['json', { outputFile: 'registration-results/results.json' }]],
  use: { baseURL: 'http://127.0.0.1:8767', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
})
