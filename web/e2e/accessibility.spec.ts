/**
 * The main views, as axe sees them: the problems a person using a keyboard, a
 * screen reader or a magnifier would run into, not every best practice.
 */
import { accessibilityProblems, expect, signIn, state, test } from './state'

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

test('a library with nested collections', async ({ page, request }) => {
  const headers = { 'Zotero-API-Key': state().key }
  const parentResponse = await request.post('/users/1/collections', {
    headers, data: [{ name: 'Accessible parent' }],
  })
  expect(parentResponse.ok()).toBe(true)
  const parent = (await parentResponse.json()).successful['0'].key
  const childResponse = await request.post('/users/1/collections', {
    headers, data: [{ name: 'Accessible child', parentCollection: parent }],
  })
  expect(childResponse.ok()).toBe(true)

  await signIn(page)
  await page.locator(`.tree__row[data-drop="collection:${parent}"] .tree__twisty`).click()
  await expect(page.getByRole('button', { name: 'Accessible child', exact: true })).toBeVisible()

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
