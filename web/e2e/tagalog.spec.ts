import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

test.use({ locale: 'tl-PH' })

test('saves a display name using translated account labels', async ({ page }, info) => {
  await signIn(page)
  await page.goto('/app/settings/profile')
  await expect(page.locator('html')).toHaveAttribute('lang', 'tl')
  const name = page.getByRole('textbox', { name: 'Pangalang ipinapakita', exact: true })
  await expect(name).toHaveValue('Ada Lovelace')
  const card = page.locator('section.card').filter({ has: name })
  try {
    await name.fill(`Pangalan ${info.project.name}`)
    await card.getByRole('button', { name: 'I-save', exact: true }).click()
    await expect(page.locator('.section-panel__notice')).toHaveText('Na-save ang pangalan.')
    await page.reload()
    await expect(name).toHaveValue(`Pangalan ${info.project.name}`)
    await expect(page.getByRole('heading', { name: 'Address ng email', exact: true })).toBeVisible()
    await page.screenshot({ path: info.outputPath('tagalog-account.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  } finally {
    await name.fill('Ada Lovelace')
    await card.getByRole('button', { name: 'I-save', exact: true }).click()
    await expect(page.locator('.section-panel__notice')).toHaveText('Na-save ang pangalan.')
  }
})

test('formats a note using translated headings and emphasis tools', async ({ page, request }, info) => {
  const marker = `Tala ${info.project.name}`
  const headers = { 'Zotero-API-Key': state().key }
  const created = await request.post('/users/1/items', {
    headers, data: [{ itemType: 'note', note: `<p>${marker}</p>` }],
  })
  expect(created.ok()).toBe(true)
  const body = await created.json()
  expect(body.failed).toEqual({})
  const key = body.successful['0'].key as string
  const note = async () => (await (await request.get(`/users/1/items/${key}`, { headers })).json()).data.note
  await signIn(page)
  await openItem(page, marker)
  const text = page.locator('.note-editor .ProseMirror')
  await text.locator('p').click({ clickCount: info.project.name === 'desktop' ? 3 : 1 })
  // The desktop button also announces the current block type.
  await page.getByRole('button', { name: /^I-format ang Teksto(?:$|:)/ }).click()
  await page.getByRole('menuitemradio', { name: 'Pamagat 1', exact: true }).click()
  await expect(text.locator('h1')).toHaveText(marker)
  await expect.poll(note).toContain(`<h1>${marker}</h1>`)
  await text.locator('h1').click({ clickCount: 3 })
  await page.keyboard.press('ControlOrMeta+a')
  await page.getByRole('button', { name: 'Makapal', exact: true }).click()
  await expect.poll(note).toContain(`<strong>${marker}</strong>`)
  await expect(page.getByRole('button', { name: 'Nakapahilis', exact: true })).toBeVisible()
  if (info.project.name === 'phone') {
    await page.getByRole('button', { name: /^I-format ang Teksto(?:$|:)/ }).click()
    await page.getByRole('menuitemcheckbox', { name: 'May guhit sa gitna', exact: true }).click()
  } else {
    await page.getByRole('button', { name: 'May guhit sa gitna', exact: true }).click()
  }
  await expect.poll(note).toContain('text-decoration: line-through')
  await page.screenshot({ path: info.outputPath('tagalog-note.png'), fullPage: true })
  expect(await accessibilityProblems(page)).toEqual([])
  await page.reload()
  await openItem(page, marker)
  await expect(text.locator('h1 strong')).toHaveText(marker)
})
