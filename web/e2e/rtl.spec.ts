import { accessibilityProblems, expect, signIn, state, test } from './state'

for (const [direction, locale] of [['ltr', 'en-US'], ['rtl', 'ar-EG']] as const) {
  test.describe(`${direction} layout`, () => {
    test.use({ locale })

    test('splitter keys and drags move both dividers in the physical direction', async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 })
      await signIn(page)
      await page.getByText('Notes on the Analytical Engine').first().click()
      await expect(page.locator('.library__detail')).toBeVisible()

      for (const pane of ['sidebar', 'detail']) {
        const grip = page.locator(`.library__grip--${pane}`)
        const center = async () => {
          const box = (await grip.boundingBox())!
          return box.x + box.width / 2
        }
        const initial = await center()
        const sidebar = (await page.locator('.library__sidebar').boundingBox())!
        const detail = (await page.locator('.library__detail').boundingBox())!
        const list = (await page.locator('.library__list').boundingBox())!
        const expected = pane === 'sidebar'
          ? direction === 'rtl' ? (sidebar.x + list.x + list.width) / 2 : (sidebar.x + sidebar.width + list.x) / 2
          : direction === 'rtl' ? (detail.x + detail.width + list.x) / 2 : (list.x + list.width + detail.x) / 2
        expect(Math.abs(initial - expected), `${pane} grip centered in its gutter`).toBeLessThan(1)

        await grip.focus()
        await page.keyboard.press('ArrowRight')
        await expect.poll(center).toBeCloseTo(initial + 16, 0)
        await page.keyboard.press('ArrowLeft')
        await expect.poll(center).toBeCloseTo(initial, 0)

        const box = (await grip.boundingBox())!
        // A longer library can scroll its top above the viewport. Press the
        // visible part of the grip, below the app header.
        const top = Math.max(box.y, 100)
        const bottom = Math.min(box.y + box.height, page.viewportSize()!.height - 20)
        const y = (top + bottom) / 2
        await page.mouse.move(initial, y)
        await page.mouse.down()
        await page.mouse.move(initial - 40, y, { steps: 5 })
        await page.mouse.up()
        await expect.poll(center).toBeCloseTo(initial - 40, 0)
      }
    })

    test('keeps a drag preview by the pointer and files the item at its drop target', async ({ page, request, isMobile }, testInfo) => {
      await page.setViewportSize({ width: 1280, height: 900 })
      const { key, book } = state()
      const headers = { 'Zotero-API-Key': key }
      const created = await request.post('/users/1/collections', {
        headers, data: [{ name: `Drop ${direction} ${testInfo.project.name}` }],
      })
      expect(created.ok()).toBe(true)
      const collection = (await created.json()).successful['0'].key
      await signIn(page)
      const row = page.getByText('Notes on the Analytical Engine').first()
      await row.evaluate((element) => element.scrollIntoView({ block: 'center' }))
      const title = (await row.boundingBox())!
      const from = { x: title.x + title.width / 2, y: title.y + title.height / 2 }
      const cursor = { x: from.x + (direction === 'rtl' ? -24 : 24), y: from.y + 10 }
      const cargo = page.locator('.library__cargo')
      const touch = isMobile ? await page.context().newCDPSession(page) : null
      const move = async (point: { x: number; y: number }) => {
        if (touch) await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point] })
        else await page.mouse.move(point.x, point.y, { steps: 5 })
      }

      if (touch) {
        await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [from] })
        // The preview appears only after the real 350ms touch hold.
        await expect(cargo).toBeVisible()
      } else {
        await page.mouse.move(from.x, from.y)
        await page.mouse.down()
      }
      await move(cursor)
      await expect(cargo).toBeVisible()
      const preview = (await cargo.boundingBox())!
      const offset = direction === 'rtl' ? cursor.x - preview.x - preview.width : preview.x - cursor.x
      const viewport = await page.evaluate(() => ({
        innerWidth: window.innerWidth,
        clientWidth: document.documentElement.clientWidth,
        clientLeft: document.documentElement.clientLeft,
        rootRight: document.documentElement.getBoundingClientRect().right,
      }))
      expect(offset, JSON.stringify({ viewport, preview, cursor })).toBeCloseTo(12, 0)
      const target = page.locator(`.tree__row[data-drop="collection:${collection}"]`)
      const box = (await target.boundingBox())!
      await move({ x: box.x + box.width / 2, y: box.y + box.height / 2 })
      await expect(target).toHaveClass(/tree__row--over/)
      const written = page.waitForResponse((response) =>
        response.request().method() === 'PATCH' && /\/web\/libraries\/\d+\/items$/.test(response.url()),
      )
      if (touch) await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
      else await page.mouse.up()
      expect((await written).ok()).toBe(true)
      await expect(cargo).toBeHidden()
      const item = await request.get(`/users/1/items/${book}`, { headers })
      expect((await item.json()).data.collections).toContain(collection)
      if (touch) await touch.detach()
    })

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
      const chevron = parentRow.locator('.tree__chevron')
      expect(await chevron.evaluate((element) => getComputedStyle(element).scale)).toBe(
        direction === 'rtl' ? '-1 1' : 'none',
      )
      await expect.poll(
        () => chevron.evaluate((element) => getComputedStyle(element).transform),
        { message: 'opening the mirrored chevron still rotates it down' },
      ).toBe('matrix(0, 1, -1, 0, 0, 0)')
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
