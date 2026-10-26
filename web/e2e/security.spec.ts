/**
 * An attachment is somebody else's file, and opening one must not let it act
 * as whoever opened it.
 */
import { expect, signIn, state, test } from './state'

test('an HTML attachment opened from the library runs nothing', async ({ page, context }) => {
  const { page: key } = state()
  await signIn(page)

  const tab = await context.newPage()
  await tab.goto(`/web/libraries/1/items/${key}/file`)

  await expect(tab).not.toHaveTitle('ran')
})

test('an HTML attachment linked with a key in the query runs nothing', async ({ page }) => {
  /* A link anybody holding a key can send to somebody signed in here. */
  const { page: key, key: apiKey } = state()
  await signIn(page)

  await page.goto(`/users/1/items/${key}/file/view?key=${apiKey}`)

  await expect(page).not.toHaveTitle('ran')
})

test('a note on a public profile is shown without its script', async ({ page }) => {
  await page.goto('/app/u/ada')
  await page.locator('.publication__summary').first().click()

  const note = page.locator('.publication__note').first()
  await expect(note).toContainText('algebraic patterns')
  expect(await note.innerHTML()).not.toMatch(/onerror/i)
})
