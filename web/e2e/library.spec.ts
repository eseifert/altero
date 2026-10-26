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

test('a field edited in the pane is still there after a reload', async ({ page }, testInfo) => {
  /* Place, which no other test reads, set to something only this project
     writes: both projects run against the one seeded library. */
  const place = `London (${testInfo.project.name})`
  await signIn(page)
  await page.getByText('Notes on the Analytical Engine').first().click()

  const row = page.locator('.detail dd').filter({ has: page.locator('[aria-labelledby$="-place"]') })
  await row.locator('.info__value').click()
  await row.locator('input').fill(place)
  await row.locator('input').press('Enter')
  await expect(row.getByRole('status')).toHaveText('Saved.')

  await page.reload()
  await page.getByText('Notes on the Analytical Engine').first().click()
  await expect(page.locator('.detail .info__value[aria-labelledby$="-place"]')).toHaveText(place)
})
