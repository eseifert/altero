/**
 * The main views, as axe sees them: the problems a person using a keyboard, a
 * screen reader or a magnifier would run into, not every best practice.
 */
import { accessibilityProblems, expect, signIn, test } from './state'

test('signing in', async ({ page }) => {
  await page.goto('/app/sign-in')
  await page.locator('input[autocomplete=username]').waitFor()

  expect(await accessibilityProblems(page)).toEqual([])
})

test('a library with an item open', async ({ page }) => {
  await signIn(page)
  await page.getByText('Notes on the Analytical Engine').first().click()
  await page.locator('.detail').waitFor()

  expect(await accessibilityProblems(page)).toEqual([])
})

test('settings', async ({ page }) => {
  await signIn(page)
  await page.goto('/app/settings')
  await page.locator('main').waitFor()

  expect(await accessibilityProblems(page)).toEqual([])
})

test('administration', async ({ page }) => {
  await signIn(page)
  await page.goto('/app/admin')
  await page.locator('main').waitFor()

  expect(await accessibilityProblems(page)).toEqual([])
})

test('a public profile', async ({ page }) => {
  await page.goto('/app/u/ada')
  await page.locator('.publication__summary').first().waitFor()

  expect(await accessibilityProblems(page)).toEqual([])
})
