import { accessibilityProblems, expect, signIn, test } from './state'

for (const [locale, direction] of [['nl', 'ltr'], ['ar', 'rtl']] as const) {
  test.describe(`group activity in ${locale}`, () => {
    test.use({ locale })

    test('separates the change description from the actor name', async ({ page }, info) => {
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('dir', direction)
      const csrf = (await page.context().cookies()).find(cookie => cookie.name === 'altero_csrf')!.value
      const headers = { 'X-CSRF-Token': decodeURIComponent(csrf) }
      const name = `Activity spacing ${locale} ${info.project.name}`
      const created = await page.request.post('/web/groups', { headers, data: { name } })
      expect(created.status()).toBe(201)
      const group = await created.json()
      try {
        const made = await page.request.post(`/web/libraries/${group.id}/items`, {
          headers, data: { itemType: 'book' },
        })
        expect(made.status()).toBe(201)
        await page.goto('/app/groups')
        await page.locator('.groups__list button').filter({ hasText: name }).click()
        const entry = page.locator('.activity__entry')
        await expect(entry).toHaveCount(1)
        const description = (await entry.locator('.activity__what').innerText()).trim()
        const actor = entry.locator('.activity__who > span')
        await expect(actor).toHaveText('Ada Lovelace')
        expect(await entry.textContent()).toContain(`${description} Ada Lovelace`)
        await entry.scrollIntoViewIfNeeded()
        await page.screenshot({ path: info.outputPath(`${locale}-activity.png`), fullPage: true })
        expect(await accessibilityProblems(page)).toEqual([])
      } finally {
        expect((await page.request.delete(`/web/groups/${group.id}`, { headers })).status()).toBe(204)
      }
    })
  })
}
