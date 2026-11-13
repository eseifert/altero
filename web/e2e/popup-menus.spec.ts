import { accessibilityProblems, expect, signIn, test } from './state'

for (const direction of ['ltr', 'rtl'] as const) {
  test(`popup menus exit with Tab and Shift+Tab (${direction})`, async ({ page }) => {
    await signIn(page)
    await expect(page.locator('.library__scopes--nested')).toBeVisible()
    await page.locator('html').evaluate((element, dir) => element.setAttribute('dir', dir), direction)
    for (const selector of ['.theme-menu__trigger', '.new-item > button']) {
      const trigger = page.locator(selector)
      for (const key of ['Tab', 'Shift+Tab']) {
        // Record the browser's own next/previous stop with the menu closed.
        await trigger.focus()
        await page.keyboard.press(key)
        await page.evaluate(() => document.activeElement?.setAttribute('data-menu-tab-target', ''))
        const target = page.locator('[data-menu-tab-target]')
        await trigger.focus()
        await page.keyboard.press('Enter')
        const menu = page.getByRole('menu')
        await expect(menu).toBeVisible()
        await page.keyboard.press('Home')
        await page.keyboard.press('ArrowDown')
        await expect(menu.locator('button').nth(1)).toBeFocused()
        await page.keyboard.press(key)
        await expect(menu).toHaveCount(0)
        await expect(target).toBeFocused()
        await target.evaluate(element => element.removeAttribute('data-menu-tab-target'))
      }
    }
    expect(await accessibilityProblems(page)).toEqual([])
  })
}
