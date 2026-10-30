import { accessibilityProblems, expect, signIn, state, test } from './state'

for (const [direction, locale] of [['ltr', 'en-US'], ['rtl', 'ar-EG']] as const) {
  test.describe(`${direction} layout`, () => {
    test.use({ locale })

    test('indents nested collections and anchors the theme menu logically', async ({ page, request, isMobile }, testInfo) => {
      const { key } = state()
      const create = async (name: string, parentCollection?: string): Promise<string> => {
        const response = await request.post('/users/1/collections', {
          headers: { 'Zotero-API-Key': key },
          data: [{ name, ...(parentCollection ? { parentCollection } : {}) }],
        })
        expect(response.ok()).toBe(true)
        const body = await response.json()
        expect(body.failed).toEqual({})
        return body.successful['0'].key
      }
      const parent = await create(`Layout ${direction} ${testInfo.project.name}`)
      const child = await create('Nested collection', parent)
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('dir', direction)

      const parentRow = page.locator(`.tree__row[data-drop="collection:${parent}"]`)
      await parentRow.locator('.tree__twisty').click()
      const childRow = page.locator(`.tree__row[data-drop="collection:${child}"]`)
      await expect(childRow).toBeVisible()
      const padding = await childRow.evaluate((element) => {
        const css = getComputedStyle(element)
        return { left: parseFloat(css.paddingLeft), right: parseFloat(css.paddingRight) }
      })
      if (direction === 'rtl') expect(padding.right).toBeGreaterThan(padding.left)
      else expect(padding.left).toBeGreaterThan(padding.right)

      if (!isMobile) {
        const sidebar = (await page.locator('.library__sidebar').boundingBox())!
        const list = (await page.locator('.library__list').boundingBox())!
        if (direction === 'rtl') expect(sidebar.x).toBeGreaterThan(list.x)
        else expect(sidebar.x).toBeLessThan(list.x)
      }

      const trigger = page.locator('.theme-menu__trigger')
      await trigger.click()
      const control = (await trigger.boundingBox())!
      const menu = (await page.locator('.theme-menu__list').boundingBox())!
      const offset = direction === 'rtl'
        ? menu.x - control.x
        : menu.x + menu.width - control.x - control.width
      expect(Math.abs(offset)).toBeLessThan(1)
      expect(menu.x).toBeGreaterThanOrEqual(0)
      expect(menu.x + menu.width).toBeLessThanOrEqual(page.viewportSize()!.width)
      await page.screenshot({ path: testInfo.outputPath(`${direction}-layout.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
    })
  })
}
