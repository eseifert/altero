import type { Locator } from '@playwright/test'

import { accessibilityProblems, expect, signIn, state, test } from './state'

async function badge(badge: Locator, container: Locator) {
  await expect(badge).toHaveText('12')
  const style = await badge.evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      background: style.backgroundColor,
      radius: parseFloat(style.borderStartStartRadius),
      width: element.getBoundingClientRect().width,
      contentWidth: element.scrollWidth,
    }
  })
  expect(style.background).not.toBe('rgba(0, 0, 0, 0)')
  expect(style.background).not.toBe(await container.evaluate((element) => getComputedStyle(element).backgroundColor))
  expect(style.radius).toBeGreaterThan(0)
  expect(style.contentWidth).toBeLessThanOrEqual(Math.ceil(style.width))
}

for (const [locale, direction] of [['en-US', 'ltr'], ['ar-EG', 'rtl']] as const) {
  test.describe(`item count badges in ${direction}`, () => {
    test.use({ locale })

    test('distinguishes collection and global tag counts in both themes', async ({ page, request }, info) => {
      const headers = { 'Zotero-API-Key': state().key }
      const name = `Count badges ${direction} ${info.project.name}`
      const made = await request.post('/users/1/collections', { headers, data: [{ name }] })
      expect(made.ok()).toBe(true)
      const collection = (await made.json()).successful['0'].key
      const items = await request.post('/users/1/items', { headers, data: Array.from({ length: 12 }, (_, index) => ({
        itemType: 'book', title: `${name} ${index}`, collections: [collection], tags: [{ tag: name }],
      })) })
      expect(items.ok()).toBe(true)
      const body = await items.json()
      expect(body.failed).toEqual({})
      const keys = Object.values(body.successful).map((item) => (item as { key: string }).key)
      try {
        await signIn(page)
        const row = page.locator('.tree__name').filter({ hasText: name })
        const pill = page.locator('.library__tag').filter({ hasText: name })
        for (const scheme of ['light', 'dark'] as const) {
          await page.emulateMedia({ colorScheme: scheme })
          await expect(page.locator('html')).toHaveAttribute('data-theme', scheme)
          await badge(row.locator('.tree__count'), row)
          await badge(pill.locator('.tag-pill__count'), pill)
          await row.click()
          await expect(row).toHaveAttribute('aria-current', 'true')
          await pill.locator('.tag-pill__name').click()
          await expect(pill.locator('.tag-pill__name')).toHaveAttribute('aria-pressed', 'true')
          await badge(row.locator('.tree__count'), row)
          await badge(pill.locator('.tag-pill__count'), pill)
          await page.locator('.library__sidebar').screenshot({ path: info.outputPath(`counts-${scheme}.png`) })
          expect(await accessibilityProblems(page)).toEqual([])
          await pill.locator('.tag-pill__name').click()
          await page.locator('.library__library').first().click()
        }
      } finally {
        for (const [kind, parameter, values] of [
          ['items', 'itemKey', keys.join(',')], ['collections', 'collectionKey', collection],
        ]) {
          const current = await request.get(`/users/1/${kind}?limit=1`, { headers })
          const removed = await request.delete(`/users/1/${kind}?${parameter}=${values}`, {
            headers: { ...headers, 'If-Unmodified-Since-Version': current.headers()['last-modified-version']! },
          })
          expect(removed.ok()).toBe(true)
        }
      }
    })
  })
}
