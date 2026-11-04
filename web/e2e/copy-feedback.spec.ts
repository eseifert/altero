import { accessibilityProblems, expect, signIn, state, test } from './state'

test('copies the displayed share link and announces success', async ({ page, context, request }, info) => {
  const headers = { 'Zotero-API-Key': state().key }
  const name = `Copy feedback ${info.project.name}`
  const made = await request.post('/users/1/collections', { headers, data: [{ name }] })
  expect(made.ok()).toBe(true)
  const key = (await made.json()).successful['0'].key as string
  try {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await signIn(page)
    await page.locator(`[data-drop="collection:${key}"]`).getByRole('button', { name: `Settings for “${name}”`, exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Share a link…', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Share this collection', exact: true })
    const create = dialog.getByRole('button', { name: 'Create a link', exact: true })
    await create.focus()
    await page.keyboard.down('Space')
    try {
      await expect.poll(() => create.evaluate((element) => getComputedStyle(element, '::after').opacity)).toBe('0.1')
    } finally {
      await page.keyboard.up('Space')
    }
    const link = dialog.getByRole('textbox', { name: 'The link', exact: true })
    await expect(link).toBeVisible()
    await dialog.getByRole('button', { name: 'Copy', exact: true }).click()
    await expect(dialog.getByRole('status')).toHaveText('Copied')
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(await link.inputValue())
    expect(await accessibilityProblems(page)).toEqual([])
    await page.screenshot({ path: info.outputPath('copied.png') })
    await dialog.getByRole('button', { name: 'Done', exact: true }).click()
  } finally {
    const current = await request.get('/users/1/collections?limit=1', { headers })
    const removed = await request.delete(`/users/1/collections/${key}`, {
      headers: { ...headers, 'If-Unmodified-Since-Version': current.headers()['last-modified-version']! },
    })
    expect(removed.ok()).toBe(true)
  }
})
