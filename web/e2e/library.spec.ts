import { expect, signIn, test } from './state'

test('a library shows what a client synced, and an item opens', async ({ page }) => {
  await signIn(page)

  await page.getByText('Notes on the Analytical Engine').first().click()

  const detail = page.locator('.detail')
  await expect(detail).toContainText('Lovelace')
  await expect(detail).toContainText('computing')
})

test('a citation is rendered by the server', async ({ page }) => {
  await signIn(page)
  await page.getByText('Notes on the Analytical Engine').first().click()

  await page.locator('.detail__button').first().click()

  await expect(page.locator('.detail__bib')).toContainText('Lovelace')
})

test('a note is shown without the script somebody put in it', async ({ page }) => {
  await signIn(page)
  await page.getByText('Notes on the Analytical Engine').first().click()

  await page.getByText('The engine weaves algebraic patterns.').first().click()

  const note = page.locator('.detail__note')
  await expect(note).toContainText('algebraic patterns')
  expect(await note.innerHTML()).not.toMatch(/onerror/i)
  expect(await page.evaluate(() => (window as unknown as { __ran?: number }).__ran)).toBeUndefined()
})
