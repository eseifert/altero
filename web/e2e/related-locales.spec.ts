import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

test.describe('Russian related-item controls', () => {
  test.use({ locale: 'ru' })

  test('adds and removes a link while keeping both records', async ({ page, request }, info) => {
    const titles = ['Source', 'Target'].map(part => `Related ${part} ru ${info.project.name}`)
    const headers = { 'Zotero-API-Key': state().key }
    const made = await request.post('/users/1/items', {
      headers, data: titles.map(title => ({ itemType: 'book', title })),
    })
    expect(made.ok()).toBe(true)
    const body = await made.json()
    expect(body.failed).toEqual({})
    const keys = ['0', '1'].map(index => body.successful[index].key as string)
    const stored = async (key: string) => {
      const response = await request.get(`/users/1/items/${key}`, { headers })
      expect(response.ok()).toBe(true)
      return (await response.json()).data
    }
    const links = async (key: string) => {
      const relation = (await stored(key)).relations?.['dc:relation']
      return (Array.isArray(relation) ? relation : relation ? [relation] : []) as string[]
    }

    await signIn(page)
    await expect(page.locator('html')).toHaveAttribute('lang', 'ru')
    await openItem(page, titles[0]!)
    const related = page.locator('.detail .related')
    await expect(related.getByRole('heading')).toHaveText('Связанные')
    await related.getByRole('button', { name: 'Добавить связанную запись', exact: true }).click()
    await related.getByRole('searchbox').fill(titles[1]!)
    const added = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith(`/items/${keys[0]}/related`))
    await related.locator('.related__search .related__item').filter({ hasText: titles[1]! }).click()
    expect((await added).status()).toBe(200)
    await expect(related.locator('.related__search')).toHaveCount(0)
    await expect(related.locator(':scope > .related__list .related__label')).toHaveText([titles[1]!])
    expect(await links(keys[0]!)).toEqual([expect.stringMatching(new RegExp(`/items/${keys[1]}$`))])
    expect(await links(keys[1]!)).toEqual([expect.stringMatching(new RegExp(`/items/${keys[0]}$`))])

    await page.reload()
    await openItem(page, titles[1]!)
    await expect(related.locator('.related__label')).toHaveText([titles[0]!])
    const remove = related.getByRole('button', { name: 'Удалить связь с записью', exact: true })
    await expect(remove).toBeVisible()
    await remove.scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath('ru-related-link.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
    const removed = page.waitForResponse(response => response.request().method() === 'DELETE'
      && new URL(response.url()).pathname.endsWith(`/items/${keys[1]}/related/${keys[0]}`))
    await remove.click()
    expect((await removed).status()).toBe(200)
    await expect(related.locator('.related__label')).toHaveCount(0)
    for (const [index, key] of keys.entries()) {
      expect(await links(key)).toEqual([])
      const item = await stored(key)
      expect(item.title).toBe(titles[index])
      expect(item.deleted ?? 0).toBe(0)
    }
    await page.reload()
    await openItem(page, titles[0]!)
    await expect(related.locator('.related__label')).toHaveCount(0)
  })
})
