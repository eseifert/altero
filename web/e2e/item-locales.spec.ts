import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

const itemControls = {
  ru: {
    create: 'Новая запись',
    shortcuts: ['Предыдущая или следующая запись', 'Первая или последняя запись', 'На десять записей вверх или вниз', 'Показать сведения о записи'],
  },
  sv: {
    create: 'Ny källa',
    shortcuts: ['Föregående eller nästa källa', 'Första eller sista källan', 'Tio källor upp eller ned', 'Visa källans detaljer'],
  },
  lv: {
    create: 'Jauns vienums',
    shortcuts: ['Iepriekšējais vai nākamais vienums', 'Pirmais vai pēdējais vienums', 'Desmit vienumi uz augšu vai leju', 'Rādīt vienuma informāciju'],
  },
  uk: {
    create: 'Новий документ',
    shortcuts: ['Попередній або наступний документ', 'Перший або останній документ', 'На десять документів вгору або вниз', 'Показати подробиці документа'],
  },
}

for (const [tag, translated] of Object.entries(itemControls)) {
  test.describe(`item controls in ${tag}`, () => {
    test.use({ locale: tag })

    test('uses the library item term in creation and keyboard help', async ({ page }, info) => {
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await page.getByRole('button', { name: translated.create, exact: true }).click()
      await expect(page.getByRole('menu', { name: translated.create, exact: true })).toBeVisible()
      await page.keyboard.press('Escape')
      await page.keyboard.press('?')
      const dialog = page.getByRole('dialog')
      for (const label of translated.shortcuts) {
        await expect(dialog.getByText(label, { exact: true })).toBeVisible()
      }
      await page.screenshot({ path: info.outputPath(`${tag}-item-shortcuts.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
    })
  })
}

test.describe('Latvian Trash confirmations', () => {
  test.use({ locale: 'lv' })

  test('names the library Trash when moving an item and restores it', async ({ page, request }, info) => {
    const title = `Latvian Trash ${info.project.name}`
    const headers = { 'Zotero-API-Key': state().key }
    const made = await request.post('/users/1/items', { headers, data: [{ itemType: 'book', title }] })
    expect(made.ok()).toBe(true)
    const body = await made.json()
    expect(body.failed).toEqual({})
    const key = body.successful['0'].key as string
    const stored = async () => {
      const response = await request.get(`/users/1/items/${key}`, { headers })
      expect(response.ok()).toBe(true)
      return (await response.json()).data
    }
    await signIn(page)
    await expect(page.locator('html')).toHaveAttribute('lang', 'lv')
    await openItem(page, title)
    await page.locator('.detail').getByRole('button', { name: 'Pārvietot uz miskasti', exact: true }).click()
    await expect(page.locator('.toasts')).toContainText('Vienumi pārvietoti uz miskasti.')
    expect((await stored()).deleted).toBe(1)
    await page.locator('.library__scope').filter({ hasText: 'Miskaste' }).click()
    await openItem(page, title)
    await page.locator('.detail').getByRole('button', { name: 'Atjaunot bibliotēkā', exact: true }).click()
    await expect(page.locator('.toasts')).toContainText('Vienumi atjaunoti.')
    expect((await stored()).deleted ?? 0).toBe(0)
    await page.screenshot({ path: info.outputPath('lv-trash-restored.png'), fullPage: true })
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
