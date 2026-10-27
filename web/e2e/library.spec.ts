import { expect, signIn, test } from './state'

test('a library shows what a client synced, and an item opens', async ({ page }) => {
  await signIn(page)

  await page.getByText('Notes on the Analytical Engine').first().click()

  const detail = page.locator('.detail')
  await expect(detail.locator('dd.creator input[aria-label="last"]').first()).toHaveValue('Lovelace')
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
  await row.locator('textarea').fill(place)
  await row.locator('textarea').press('Enter')
  await expect(row.getByRole('status')).toHaveText('Saved.')

  await page.reload()
  await page.getByText('Notes on the Analytical Engine').first().click()
  await expect(page.locator('.detail .info__value[aria-labelledby$="-place"]')).toHaveText(place)
})

test('a creator dragged by its grip moves, and stays moved', async ({ page }) => {
  /* Both projects drag the same item, so this checks that the two swap
     whichever order the other project left them in. */
  await signIn(page)
  await page.getByText('Sketch of the Analytical Engine').first().click()
  const lastNames = () =>
    page.locator('.detail dd.creator input[aria-label="last"]').evaluateAll((inputs) =>
      inputs.map((input) => (input as HTMLInputElement).value),
    )
  const before = await lastNames()
  expect(before).toHaveLength(2)

  // On a phone the panes are stacked, and the creators are below the fold.
  const grips = page.locator('.detail .creator__grip')
  await grips.nth(1).scrollIntoViewIfNeeded()
  const from = (await grips.nth(1).boundingBox())!
  const to = (await page.locator('.detail dd.creator').first().boundingBox())!
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + 20, to.y + to.height / 2, { steps: 8 })
  await page.mouse.up()

  await expect.poll(lastNames).toEqual([before[1], before[0]])
  await page.reload()
  await page.getByText('Sketch of the Analytical Engine').first().click()
  await expect.poll(lastNames).toEqual([before[1], before[0]])
})

test('a creator is renamed in place', async ({ page }, testInfo) => {
  const first = `Luigi (${testInfo.project.name})`
  await signIn(page)
  await page.getByText('Sketch of the Analytical Engine').first().click()

  const name = page.locator('.detail dd.creator input[aria-label="first"]').first()
  await name.scrollIntoViewIfNeeded()
  await name.fill(first)
  await name.press('Enter')

  // Whichever row it is in: the other project may have reordered them.
  await page.reload()
  await page.getByText('Sketch of the Analytical Engine').first().click()
  await expect
    .poll(() =>
      page
        .locator('.detail dd.creator input[aria-label="first"]')
        .evaluateAll((inputs) => inputs.map((input) => (input as HTMLInputElement).value)),
    )
    .toContain(first)
})
