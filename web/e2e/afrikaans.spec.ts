import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

test.use({ locale: 'af-ZA' })

test('uses formal address when changing an item type and a file extension', async ({ page, request }, info) => {
  const title = `Afrikaans confirmations ${info.project.name}`
  const headers = { 'Zotero-API-Key': state().key }
  const made = await request.post('/users/1/items', { headers, data: [{ itemType: 'book', title, edition: '2' }] })
  expect(made.ok()).toBe(true)
  const body = await made.json()
  expect(body.failed).toEqual({})
  const key = body.successful['0'].key as string
  const stored = async () => (await (await request.get(`/users/1/items/${key}`, { headers })).json()).data
  await signIn(page)
  await expect(page.locator('html')).toHaveAttribute('lang', 'af')
  await openItem(page, title)
  await page.locator('.info__type').selectOption('journalArticle')
  const typeDialog = page.getByRole('alertdialog', { name: 'Verander itemtipe', exact: true })
  await expect(typeDialog).toContainText('Is u seker u wil die itemtipe verander?')
  expect((await stored()).itemType).toBe('book')
  expect(await accessibilityProblems(page)).toEqual([])
  await typeDialog.getByRole('button', { name: 'Verander', exact: true }).click()
  await expect.poll(async () => (await stored()).itemType).toBe('journalArticle')
  expect((await stored()).edition).toBeUndefined()

  const attach = page.locator('.detail').getByRole('button', { name: 'Voeg aanhegsel by', exact: true })
  await attach.scrollIntoViewIfNeeded()
  await expect(async () => {
    if ((await attach.getAttribute('aria-expanded')) !== 'true') await attach.click()
    await expect(page.getByRole('menu', { name: 'Voeg aanhegsel by' })).toBeVisible({ timeout: 500 })
  }).toPass()
  const bytes = Buffer.from(`%PDF-1.7\n${title}\n`)
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('menuitem', { name: 'Heg lêer aan…', exact: true }).click()
  await (await chooser).setFiles({ name: 'paper.pdf', mimeType: 'application/pdf', buffer: bytes })
  await page.locator('.detail__children').getByText('PDF', { exact: true }).click()
  await page.getByRole('button', { name: 'Lêernaam', exact: true }).click()
  await page.keyboard.press('ControlOrMeta+a')
  await page.keyboard.type('paper.txt')
  await page.keyboard.press('Enter')
  const rename = page.getByRole('alertdialog', { name: 'Lêernaam', exact: true })
  await expect(rename).toContainText('Is u seker u wil die lêeruitbreiding van “.pdf” na “.txt” verander?')
  await expect(rename).toContainText('As u die uitbreiding verander, kan die lêer in ’n ander toepassing oopmaak.')
  await page.screenshot({ path: info.outputPath('afrikaans-extension.png'), fullPage: true })
  expect(await accessibilityProblems(page)).toEqual([])
  await rename.getByRole('button', { name: 'Gebruik .txt', exact: true }).click()
  const children = async () => (await (await request.get(`/users/1/items/${key}/children`, { headers })).json())
  await expect.poll(async () => (await children())[0].data.filename).toBe('paper.txt')
  const [file] = await children()
  const download = await request.get(`/users/1/items/${file.key}/file`, { headers })
  expect(download.ok()).toBe(true)
  expect(download.headers()['content-disposition']).toContain('paper.txt')
  expect(await download.body()).toEqual(bytes)
})
