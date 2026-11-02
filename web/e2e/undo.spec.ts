import { accessibilityProblems, expect, signIn, state, test } from './state'

async function api(path: string, method = 'GET', body?: unknown) {
  const { baseURL, key } = state()
  const response = await fetch(`${baseURL}/users/1/${path}`, {
    method,
    headers: { 'Zotero-API-Key': key, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  expect(response.ok).toBeTruthy()
  return response.json()
}

async function makeItem(title: string, collections: string[] = []): Promise<string> {
  const made = await api('items', 'POST', [{ itemType: 'book', title, collections }])
  expect(made.failed).toEqual({})
  return made.successful['0'].key
}

test('trash undo stays reachable with keyboard focus and survives a reload', async ({ page }, info) => {
  const title = `Undo trash (${info.project.name})`
  const key = await makeItem(title)
  await signIn(page)
  await page.locator('.library__row').filter({ hasText: title }).click()
  await page.locator('.detail').getByRole('button', { name: 'Move to trash', exact: true }).click()

  const toast = page.locator('.toast').filter({ hasText: 'Items moved to trash.' })
  const undo = toast.getByRole('button', { name: 'Undo', exact: true })
  await expect(undo).toBeVisible()
  await expect(page.locator('.library__row').filter({ hasText: title })).toHaveCount(0)
  await undo.focus()
  await page.mouse.move(1, 1)
  await page.clock.install()
  await page.clock.fastForward(12000)
  await expect(undo).toBeVisible()
  expect(await accessibilityProblems(page)).toEqual([])
  await undo.press('Enter')
  await expect(page.locator('.toasts')).toContainText('Change undone.')
  await expect(page.locator('.library__row').filter({ hasText: title })).toHaveCount(1)
  expect((await api(`items/${key}`)).data.deleted).toBeUndefined()
  await page.reload()
  await expect(page.locator('.library__row').filter({ hasText: title })).toBeVisible()
})

test('filing undo preserves a membership the selection already had', async ({ page }, info) => {
  const name = `Undo filing (${info.project.name})`
  const made = await api('collections', 'POST', [{ name }])
  const collection = made.successful['0'].key as string
  const firstTitle = `Undo first (${info.project.name})`
  const secondTitle = `Undo second (${info.project.name})`
  const first = await makeItem(firstTitle)
  const second = await makeItem(secondTitle, [collection])
  await signIn(page)
  await page.getByRole('button', { name: 'Select', exact: true }).click()
  await page.locator('.library__row').filter({ hasText: firstTitle }).click()
  await page.locator('.library__row').filter({ hasText: secondTitle }).click()
  await page.locator('.selection').getByRole('button', { name: 'Move or copy…', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox').selectOption(`place:${collection}`)
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  const toast = page.locator('.toast').filter({ hasText: 'Items filed.' })
  await toast.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(page.locator('.toasts')).toContainText('Change undone.')
  expect((await api(`items/${first}`)).data.collections).toEqual([])
  expect((await api(`items/${second}`)).data.collections).toEqual([collection])
  await page.reload()
  await page.locator(`[data-drop="collection:${collection}"] .tree__name`).click()
  await expect(page.locator('.library__row').filter({ hasText: firstTitle })).toHaveCount(0)
  await expect(page.locator('.library__row').filter({ hasText: secondTitle })).toHaveCount(1)
})

test('a later sync makes an old undo refuse without restoring the item', async ({ page }, info) => {
  const title = `Stale undo (${info.project.name})`
  const key = await makeItem(title)
  await signIn(page)
  await page.locator('.library__row').filter({ hasText: title }).click()
  await page.locator('.detail').getByRole('button', { name: 'Move to trash', exact: true }).click()
  const undo = page.locator('.toast').getByRole('button', { name: 'Undo', exact: true })
  await expect(undo).toBeVisible()
  await makeItem(`Synced meanwhile (${info.project.name})`)
  await undo.click()
  await expect(page.locator('.toasts')).toContainText('Undo is no longer available because the library changed.')
  expect((await api(`items/${key}`)).data.deleted).toBe(1)
  await expect(page.locator('.library__row').filter({ hasText: title })).toHaveCount(0)
})

test('undo brings a child note back into its open parent with reduced motion', async ({ page }, info) => {
  const title = `Undo note parent (${info.project.name})`
  const noteTitle = `Undo child (${info.project.name})`
  const parent = await makeItem(title)
  await api('items', 'POST', [{ itemType: 'note', parentItem: parent, note: `<p>${noteTitle}</p>` }])
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await signIn(page)
  await page.locator('.library__row').filter({ hasText: title }).click()
  const child = page.locator('.detail__child').filter({ hasText: noteTitle })
  await child.click()
  await page.locator('.detail').getByRole('button', { name: 'Move to trash', exact: true }).click()
  await expect(page.locator('.detail__title')).toHaveText(title)
  await expect(child).toHaveCount(0)
  await page.locator('.toast').getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(child).toBeVisible()
  await page.reload()
  await page.locator('.library__row').filter({ hasText: title }).click()
  await expect(child).toBeVisible()
})
