import type { Locator, Page } from '@playwright/test'

import { accessibilityProblems, expect, libraryRow, signIn, state, test } from './state'

interface Pulse {
  target: string | null
  animation: string
  duration: string
  background: string
  shadow: string
  transition: string
}

/** Real touch holds on phones, real mouse movement on desktop. */
async function begin(page: Page, row: Locator, isMobile: boolean) {
  await row.evaluate((element) => element.scrollIntoView({ block: 'center' }))
  const box = (await row.boundingBox())!
  const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  const touch = isMobile ? await page.context().newCDPSession(page) : null
  if (touch) {
    await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [from] })
    await expect(page.locator('.library__cargo')).toBeVisible()
  } else {
    await page.mouse.move(from.x, from.y)
    await page.mouse.down()
    await page.mouse.move(from.x + 10, from.y + 10)
  }
  return {
    async over(target: Locator) {
      await target.evaluate((element) => element.scrollIntoView({ block: 'center' }))
      const box = (await target.boundingBox())!
      const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
      if (touch) await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point] })
      else await page.mouse.move(point.x, point.y, { steps: 5 })
    },
    async end(cancel = false) {
      if (touch) {
        await touch.send('Input.dispatchTouchEvent', { type: cancel ? 'touchCancel' : 'touchEnd', touchPoints: [] })
        await touch.detach()
      } else {
        if (cancel) await page.keyboard.press('Escape')
        await page.mouse.up()
      }
    },
  }
}

/** Preserve evidence of the short pulse even if the assertion runs after it. */
async function observe(page: Page) {
  await page.evaluate(() => {
    const pulses: Pulse[] = []
    Object.assign(window, { dropPulses: pulses })
    new MutationObserver((records) => {
      for (const record of records) {
        const element = record.target as HTMLElement
        if (element.classList.contains('drop-confirmed') && !record.oldValue?.includes('drop-confirmed')) {
          const css = getComputedStyle(element)
          // Sample painted frames rather than the class mutation instant.
          const animation = css.animationName
          requestAnimationFrame(() => requestAnimationFrame(() => {
            if (!element.classList.contains('drop-confirmed')) return
            pulses.push({
              target: element.getAttribute('data-drop'), animation,
              duration: css.animationDuration, background: css.backgroundColor, shadow: css.boxShadow,
              transition: css.transitionProperty,
            })
          }))
        }
      }
    }).observe(document.querySelector('.library__sidebar')!, {
      subtree: true, attributes: true, attributeFilter: ['class'], attributeOldValue: true,
    })
  })
}

async function pulses(page: Page) {
  return page.evaluate(() => (window as unknown as {
    dropPulses: Pulse[]
  }).dropPulses)
}

for (const [direction, locale] of [['ltr', 'en-US'], ['rtl', 'ar-EG']] as const) {
  test.describe(`${direction} drag feedback`, () => {
    test.use({ locale })

    for (const reducedMotion of ['no-preference', 'reduce'] as const) {
      test(`counts the selection and confirms only saved drops, ${reducedMotion}`, async ({ page, request, isMobile }, info) => {
        await page.emulateMedia({ reducedMotion })
        const headers = { 'Zotero-API-Key': state().key }
        const name = `Drag ${direction} ${reducedMotion} ${info.project.name}`
        // On phones, allow source and destination to scroll to the viewport
        // center. Releasing at the same screen position still produces a click.
        const preceding = isMobile ? 20 : 0
        const made = await request.post('/users/1/collections', { headers, data: [
          ...Array.from({ length: preceding }, (_, index) => ({ name: `Before ${name} ${index}` })),
          { name },
        ] })
        expect(made.ok()).toBe(true)
        const collections = (await made.json()).successful as Record<string, { key: string }>
        const collection = collections[String(preceding)]!.key
        const filler: string[] = []
        if (isMobile) {
          const filled = await request.post('/users/1/items', { headers, data:
            Array.from({ length: 50 }, (_, index) => ({
              itemType: 'book', title: `After ${name} ${index}`, dateModified: '2000-01-01T00:00:00Z',
            })),
          })
          expect(filled.ok()).toBe(true)
          filler.push(...Object.values((await filled.json()).successful as Record<string, { key: string }>).map((item) => item.key))
        }
        let release = () => {}
        try {
          await signIn(page)
          const book = await libraryRow(page, 'Notes on the Analytical Engine')
          const second = await libraryRow(page, 'On the Economy of Machinery and Manufactures')
          await book.click()
          await second.click({ modifiers: ['ControlOrMeta'] })
          const selected = page.locator('.library__row--selected')
          await expect(selected).toHaveCount(2)
          const keys = await selected.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-row')!))
          await observe(page)

          const held = new Promise<void>((resolve) => { release = resolve })
          let arrived!: () => void
          const requested = new Promise<void>((resolve) => { arrived = resolve })
          await page.route('**/web/libraries/*/items', async (route) => {
            if (route.request().method() !== 'PATCH') return route.continue()
            arrived()
            await held
            await route.continue()
          })
          const drag = await begin(page, book, isMobile)
          await expect(page.locator('.library__cargo .count-badge')).toHaveText('2')
          const target = page.locator(`[data-drop="collection:${collection}"]`)
          await drag.over(target)
          await expect(target).toHaveClass(/tree__row--over/)
          await page.screenshot({ path: info.outputPath(`drag-${direction}.png`) })
          await drag.end()
          await requested
          await expect(page.locator('.library__cargo')).toBeHidden()
          expect(await pulses(page)).toEqual([])
          release()
          await expect.poll(() => pulses(page)).toHaveLength(1)
          const pulse = (await pulses(page))[0]!
          expect(pulse.target).toBe(`collection:${collection}`)
          expect(pulse.shadow).not.toBe('none')
          expect(pulse.transition).toBe('none')
          expect(pulse.background).not.toBe('rgba(0, 0, 0, 0)')
          if (reducedMotion === 'reduce') expect(pulse.animation).toBe('none')
          else {
            expect(pulse.animation).toContain('drop-confirmation')
            expect(pulse.duration).toBe('0.25s')
          }
          await expect(target).not.toHaveClass(/drop-confirmed|tree__row--over/)
          await expect(selected).toHaveCount(2)
          for (const key of keys) {
            const item = await request.get(`/users/1/items/${key}`, { headers })
            expect((await item.json()).data.collections).toContain(collection)
          }
          expect(await accessibilityProblems(page)).toEqual([])
        } finally {
          release()
          await page.unrouteAll({ behavior: 'ignoreErrors' })
          const current = await request.get('/users/1/collections?limit=1', { headers })
          const keys = Object.values(collections).map((entry) => entry.key)
          const removed = await request.delete(`/users/1/collections?collectionKey=${keys.join(',')}`, {
            headers: { ...headers, 'If-Unmodified-Since-Version': current.headers()['last-modified-version']! },
          })
          expect(removed.ok()).toBe(true)
          if (filler.length) {
            const cleared = await request.delete(`/users/1/items?itemKey=${filler.join(',')}`, {
              headers: { ...headers, 'If-Unmodified-Since-Version': removed.headers()['last-modified-version']! },
            })
            expect(cleared.ok()).toBe(true)
          }
        }
      })
    }

    test('cancellation and refused writes do not confirm or change the item', async ({ page, request, isMobile }) => {
      await signIn(page)
      await observe(page)
      const row = await libraryRow(page, 'On the Economy of Machinery and Manufactures')
      const target = page.locator('[data-drop="trash:"]')
      let writes = 0
      await page.route('**/web/libraries/*/items', async (route) => {
        if (route.request().method() !== 'PATCH') return route.continue()
        writes += 1
        await route.fulfill({ status: 403, json: { message: 'Drop refused' } })
      })
      const cancelled = await begin(page, row, isMobile)
      await cancelled.over(target)
      await expect(target).toHaveClass(/library__scope-row--over/)
      await cancelled.end(true)
      await expect(page.locator('.library__cargo')).toBeHidden()
      expect(writes).toBe(0)
      const refused = await begin(page, row, isMobile)
      await refused.over(target)
      await refused.end()
      await expect(page.getByText('Drop refused', { exact: true })).toBeVisible()
      expect(writes).toBe(1)
      expect(await pulses(page)).toEqual([])
      const key = await row.getAttribute('data-row')
      const item = await request.get(`/users/1/items/${key}`, { headers: { 'Zotero-API-Key': state().key } })
      expect((await item.json()).data.deleted).toBeUndefined()
    })
  })
}
