/** What `setup.ts` made, and the helpers every test shares. */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import AxeBuilder from '@axe-core/playwright'
import { expect, type Page, test as base } from '@playwright/test'

export const USERNAME = 'ada'
export const PASSWORD = 'correct horse battery staple'
export const STATE_FILE = join(import.meta.dirname, '.state.json')

export interface State {
  baseURL: string
  key: string
  /** A published book, with the two children below. */
  book: string
  /** A child note carrying an image with a handler. */
  note: string
  /** A child HTML attachment whose script sets the document title. */
  page: string
}

export function state(): State {
  return JSON.parse(readFileSync(STATE_FILE, 'utf8')) as State
}

/**
 * The one violation that is the policy working rather than the page breaking.
 *
 * Chrome reports an inline handler as soon as markup carrying one is parsed,
 * even into an inert document where nothing can run -- and parsing a note is
 * how the sanitizer finds the handler to remove. The tests that show a note
 * check separately that nothing ran.
 */
const EXPECTED = /^script-src-attr inline at \S*\/assets\/sanitize-[\w-]+\.js:/

/**
 * Every test fails if the page broke the Content-Security-Policy.
 *
 * The listener goes in before any of the page's own script, so a violation
 * during start-up is caught as well as one later on.
 */
export const test = base.extend<{ violations: string[] }>({
  violations: [
    async ({ page }, use) => {
      await page.addInitScript(() => {
        document.addEventListener('securitypolicyviolation', (event) => {
          const seen = ((window as unknown as { __csp?: string[] }).__csp ??= [])
          seen.push(
            `${event.violatedDirective} ${event.blockedURI} at ${event.sourceFile}:${event.lineNumber} ${event.sample}`,
          )
        })
      })
      const violations: string[] = []
      await use(violations)
      violations.push(
        ...(await page
          .evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? [])
          .catch(() => [])),
      )
      expect(violations.filter((found) => !EXPECTED.test(found)), 'CSP violations').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }

export async function signIn(page: Page): Promise<void> {
  await page.goto('/app/sign-in')
  await page.locator('input[autocomplete=username]').fill(USERNAME)
  await page.locator('input[autocomplete=current-password]').fill(PASSWORD)
  await page.locator('button[type=submit]').click()
  await page.waitForURL(/\/app\/library/)
}

/** What axe finds that a person would trip over, rather than every best practice. */
export async function accessibilityProblems(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  return results.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map(
      (violation) =>
        `${violation.id} (${violation.impact}): ${violation.help} — ` +
        violation.nodes.map((node) => node.target.join(' ')).join(', '),
    )
}
