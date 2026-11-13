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

for (const mode of ['native', 'no-popover', 'no-anchor'] as const) {
  for (const direction of ['ltr', 'rtl'] as const) {
    test(`theme menu uses ${mode} positioning (${direction})`, async ({ page }, info) => {
      if (mode === 'no-popover') await page.addInitScript(() => {
        delete (HTMLElement.prototype as Partial<HTMLElement>).popover
      })
      if (mode === 'no-anchor') await page.addInitScript(() => {
        const supports = CSS.supports.bind(CSS)
        CSS.supports = (property: string, value?: string) => property === 'anchor-name'
          ? false : value === undefined ? supports(property) : supports(property, value)
      })
      await signIn(page)
      await expect(page.locator('.library__scopes--nested')).toBeVisible()
      await page.setViewportSize({ width: 320, height: 360 })
      await page.locator('html').evaluate((element, dir) => element.setAttribute('dir', dir), direction)
      const trigger = page.locator('.theme-menu__trigger')
      const menu = page.getByRole('menu', { name: 'Color theme', exact: true })
      if (mode === 'native') {
        // An anchor near both viewport edges must flip above its trigger.
        await trigger.evaluate(element => {
          const style = (element as HTMLElement).style
          style.position = 'fixed'
          // Keep the source fully visible, including mobile RTL auto-fit.
          style.insetBlockEnd = '1rem'
          style.insetInlineEnd = '1rem'
        })
      }
      await trigger.click()
      await expect(menu).toBeVisible()
      if (mode === 'native') {
        // Enlarge this menu's text without overflowing the unrelated app shell.
        await menu.locator('button').evaluateAll(buttons => {
          for (const button of buttons) button.style.fontSize = '1.25rem'
        })
        await expect(menu).toHaveAttribute('popover', 'auto')
        expect(await menu.evaluate(element => element.matches(':popover-open'))).toBe(true)
        const box = (await menu.boundingBox())!
        const button = (await trigger.boundingBox())!
        // Mobile auto-fit can make a 320px device viewport wider in CSS pixels.
        // Compare CSS bounding boxes with the browser's actual visible viewport.
        const viewport = await page.evaluate(() => ({
          x: visualViewport?.offsetLeft ?? 0, y: visualViewport?.offsetTop ?? 0,
          width: visualViewport?.width ?? innerWidth,
        }))
        expect(button.x).toBeGreaterThanOrEqual(viewport.x - 1)
        expect(button.x + button.width).toBeLessThanOrEqual(viewport.x + viewport.width + 1)
        expect(box.x).toBeGreaterThanOrEqual(viewport.x - 1)
        expect(box.x + box.width).toBeLessThanOrEqual(viewport.x + viewport.width + 1)
        expect(box.y).toBeGreaterThanOrEqual(viewport.y - 1)
        expect(box.y + box.height).toBeLessThanOrEqual(button.y)
        if (direction === 'ltr' && info.project.name === 'desktop') {
          await page.screenshot({ path: info.outputPath('theme-menu.png') })
        }
        // Native dismissal must update Vue's state and its ARIA promise.
        await menu.evaluate(element => (element as HTMLElement).hidePopover())
        await expect(menu).toHaveCount(0)
        await expect(trigger).toHaveAttribute('aria-expanded', 'false')
      } else {
        await expect(menu).not.toHaveAttribute('popover')
        await page.keyboard.press('Escape')
        await expect(menu).toHaveCount(0)
      }
      await trigger.press('ArrowDown')
      await expect(menu.getByRole('menuitemradio').first()).toBeFocused()
      await page.keyboard.press('End')
      await expect(menu.getByRole('menuitemradio').last()).toBeFocused()
      await page.keyboard.press('Escape')
      await expect(menu).toHaveCount(0)
      await expect(trigger).toBeFocused()
      await trigger.click()
      await expect(menu).toBeVisible()
      await trigger.click()
      await expect(menu).toHaveCount(0)
      await trigger.click()
      await page.locator('.shell__brand').click()
      await expect(menu).toHaveCount(0)
      expect(await accessibilityProblems(page)).toEqual([])
    })
  }
}
