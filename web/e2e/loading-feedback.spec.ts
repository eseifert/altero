import { accessibilityProblems, expect, signIn, test } from './state'

for (const locale of ['en-US', 'ar-EG']) {
  test.describe(`loading feedback in ${locale}`, () => {
    test.use({ locale })

    for (const reducedMotion of ['no-preference', 'reduce'] as const) {
      test(`shows loading shapes and responds to button presses, ${reducedMotion}`, async ({ page, isMobile }, info) => {
        await page.emulateMedia({ reducedMotion })
        let release!: () => void
        const held = new Promise<void>((resolve) => { release = resolve })
        await page.route(/\/web\/libraries\/\d+\/items(?:\?|$)/, async (route) => {
          await held
          await route.continue()
        })
        try {
          await signIn(page)
          const skeleton = page.locator('.library__skeleton')
          await expect(skeleton).toBeVisible()
          await expect(skeleton).toHaveAttribute('aria-hidden', 'true')
          await expect(skeleton.locator('.library__row')).toHaveCount(8)
          await expect(skeleton.getByRole('button')).toHaveCount(0)
          await expect(page.locator('.library__state[role="status"]')).not.toHaveText('')
          const shimmer = await skeleton.locator('.skeleton').first().evaluate((element) => {
            const css = getComputedStyle(element)
            return { duration: parseFloat(css.animationDuration), image: css.backgroundImage, width: element.getBoundingClientRect().width }
          })
          expect(shimmer.width).toBeGreaterThan(0)
          if (reducedMotion === 'reduce') {
            expect(shimmer.duration).toBeLessThanOrEqual(0.001)
            expect(shimmer.image).toBe('none')
          } else expect(shimmer.duration).toBeGreaterThan(1)
          expect(await accessibilityProblems(page)).toEqual([])
          await skeleton.scrollIntoViewIfNeeded()
          await expect(skeleton.locator('.library__row').first()).toBeInViewport()
          await page.screenshot({ path: info.outputPath('loading.png') })
        } finally {
          release()
        }
        await expect(page.locator('.library__skeleton')).toHaveCount(0)
        await expect(page.locator('.library__items [data-row]').first()).toBeVisible()
        await page.unrouteAll({ behavior: 'wait' })
        await page.bringToFront()
        // Press Search with touch or a mouse. The layer is
        // visible before releasing and does not shift the control's bounds.
        const button = page.locator('.library__search .icon-button')
        await button.evaluate((element) => element.scrollIntoView({ block: 'center' }))
        const before = (await button.boundingBox())!
        const point = { x: before.x + before.width / 2, y: before.y + before.height / 2 }
        expect(await button.evaluate((element, point) => element.contains(document.elementFromPoint(point.x, point.y)), point)).toBe(true)
        const touch = isMobile ? await page.context().newCDPSession(page) : null
        try {
          if (touch) await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] })
          else { await page.mouse.move(point.x, point.y); await page.mouse.down() }
          await expect.poll(() => button.evaluate((element) => {
            const css = getComputedStyle(element, '::after')
            return { content: css.content, opacity: css.opacity }
          }), { intervals: [16, 32, 50] }).toEqual({ content: '""', opacity: '0.1' })
          expect(await button.boundingBox()).toEqual(before)
        } finally {
          if (touch) {
            await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
            await touch.detach()
          } else await page.mouse.up()
        }
        await expect(page.locator('.library__search-field')).toBeFocused()
        await page.keyboard.press('Escape')
        await button.focus()
        await page.keyboard.down('Space')
        try {
          await expect.poll(() => button.evaluate((element) => getComputedStyle(element, '::after').opacity)).toBe('0.1')
        } finally {
          await page.keyboard.up('Space')
        }
        await expect(page.locator('.library__search-field')).toBeFocused()
        await page.keyboard.press('Escape')
        expect(await accessibilityProblems(page)).toEqual([])
      })
    }
  })
}
