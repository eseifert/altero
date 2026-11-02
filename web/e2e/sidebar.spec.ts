import { accessibilityProblems, expect, signIn, state, test } from './state'

for (const [locale, direction] of [['en-US', 'ltr'], ['ar-EG', 'rtl']] as const) {
  test.describe(`library navigation in ${direction}`, () => {
    test.use({ locale })

    test('aligns libraries and shares the group icon without a heading or vertical guide', async ({ page }, info) => {
      const name = `Sidebar group ${direction} ${info.project.name}`
      const { baseURL, key } = state()
      const created = await fetch(`${baseURL}/groups`, {
        method: 'POST', headers: { 'Zotero-API-Key': key, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      expect(created.status).toBe(201)
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('dir', direction)
      const sidebar = page.locator('.library__sidebar')
      const libraries = sidebar.locator('.library__libraries')
      await expect(libraries.getByRole('heading')).toHaveCount(0)
      const personal = libraries.locator('.library__nav-row').first()
      const group = libraries.locator('.library__nav-row').filter({ hasText: name })
      const first = (await personal.boundingBox())!
      const second = (await group.boundingBox())!
      expect(Math.abs(first.x - second.x)).toBeLessThan(1)
      expect(Math.abs(first.width - second.width)).toBeLessThan(1)
      const settingsIcon = await page.locator('a[href="/app/groups"] svg g').innerHTML()
      expect(await group.locator('.library__library svg g').innerHTML()).toBe(settingsIcon)
      await expect(libraries.locator('.library__scopes--nested')).toHaveCSS('border-inline-start-width', '0px')
      await group.locator('.library__library').click()
      await expect(libraries.locator('.library__scopes--nested')).toHaveAttribute('aria-label', name)
      await expect(libraries.locator('.library__scopes--nested')).toHaveCSS('border-inline-start-width', '0px')
      await sidebar.screenshot({ path: info.outputPath(`libraries-${direction}.png`) })
      expect(await accessibilityProblems(page)).toEqual([])
    })
  })
}
