import { expect, openItem, signIn, state, test } from './state'

test('regional browser preferences boot without Object.hasOwn', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(Object, 'hasOwn', { configurable: true, value: undefined })
    Object.defineProperty(navigator, 'languages', { value: ['en-AU'] })
  })
  await signIn(page)
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-GB')
})

test('notes open and save without Object.hasOwn', async ({ page }, info) => {
  const { baseURL, key } = state()
  const title = `Browser capability ${info.project.name}`
  const headers = { 'Zotero-API-Key': key, 'Content-Type': 'application/json' }
  const made = await fetch(`${baseURL}/users/1/items`, {
    method: 'POST', headers,
    body: JSON.stringify([{ itemType: 'note', note: `<p>${title}</p>` }]),
  })
  expect(made.ok).toBe(true)
  const result = await made.json()
  expect(result.failed).toEqual({})
  const itemKey: string = result.successful['0'].key

  await signIn(page)
  await page.evaluate(() => Object.defineProperty(Object, 'hasOwn', { value: undefined }))
  await openItem(page, title)
  const editor = page.locator('.note-editor .ProseMirror')
  await expect(editor).toHaveText(title)
  await editor.click()
  await page.keyboard.press('End')
  await page.keyboard.type(' edited')
  await expect(page.locator('.note-pane__state')).toHaveText('Saved.')
  const saved = await fetch(`${baseURL}/users/1/items/${itemKey}`, { headers })
  expect((await saved.json()).data.note).toContain(`<p>${title} edited</p>`)
})
