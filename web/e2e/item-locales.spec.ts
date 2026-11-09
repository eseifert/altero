import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

test.describe('Swedish item controls', () => {
  test.use({ locale: 'sv' })

  test('uses the library item term in creation and keyboard help', async ({ page }, info) => {
    await signIn(page)
    await expect(page.locator('html')).toHaveAttribute('lang', 'sv')
    await page.getByRole('button', { name: 'Ny källa', exact: true }).click()
    await expect(page.getByRole('menu', { name: 'Ny källa', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await page.keyboard.press('?')
    const dialog = page.getByRole('dialog')
    for (const label of [
      'Föregående eller nästa källa',
      'Första eller sista källan',
      'Tio källor upp eller ned',
      'Visa källans detaljer',
    ]) {
      await expect(dialog.getByText(label, { exact: true })).toBeVisible()
    }
    await page.screenshot({ path: info.outputPath('sv-item-shortcuts.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  })
})

test.describe('Romanian item confirmations', () => {
  test.use({ locale: 'ro' })

  test('keeps the library item term after filing, trashing and restoring', async ({ page, request }, info) => {
    const title = `Romanian item actions ${info.project.name}`
    const headers = { 'Zotero-API-Key': state().key }
    const made = await request.post('/users/1/items', { headers, data: [{ itemType: 'book', title }] })
    expect(made.ok()).toBe(true)
    const items = await made.json()
    expect(items.failed).toEqual({})
    const key = items.successful['0'].key as string
    const created = await request.post('/users/1/collections', { headers, data: [{ name: title }] })
    expect(created.ok()).toBe(true)
    const collections = await created.json()
    expect(collections.failed).toEqual({})
    const collection = collections.successful['0'].key as string
    const stored = async () => {
      const response = await request.get(`/users/1/items/${key}`, { headers })
      expect(response.ok()).toBe(true)
      return (await response.json()).data
    }

    await signIn(page)
    await expect(page.locator('html')).toHaveAttribute('lang', 'ro')
    await openItem(page, title)
    await page.locator('.detail').getByRole('button', { name: 'Mută sau copiază…', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('combobox').selectOption(`place:${collection}`)
    await dialog.getByRole('button', { name: 'Salvează', exact: true }).click()
    await expect(page.locator('.toasts')).toContainText('Înregistrările au fost organizate.')
    expect((await stored()).collections).toEqual([collection])

    await page.locator('.detail').getByRole('button', { name: 'Mută în coșul de gunoi', exact: true }).click()
    await expect(page.locator('.toasts')).toContainText('Înregistrările au fost mutate la coș.')
    expect((await stored()).deleted).toBe(1)
    await page.locator('.library__scope').filter({ hasText: 'Coș de gunoi' }).click()
    await openItem(page, title)
    await page.locator('.detail').getByRole('button', { name: 'Restaurează la bibliotecă', exact: true }).click()
    await expect(page.locator('.toasts')).toContainText('Înregistrările au fost restaurate.')
    const restored = await stored()
    expect(restored.deleted ?? 0).toBe(0)
    expect(restored.collections).toEqual([collection])
    await page.screenshot({ path: info.outputPath('ro-item-confirmations.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  })
})
