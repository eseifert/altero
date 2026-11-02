import type { Locator } from '@playwright/test'

import { accessibilityProblems, expect, signIn, state, test } from './state'

async function api(path: string, body?: unknown) {
  const { baseURL, key } = state()
  const response = await fetch(`${baseURL}/users/1/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Zotero-API-Key': key, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  expect(response.ok).toBe(true)
  return response.json()
}

async function appearance(pill: Locator) {
  return pill.evaluate((element) => {
    const style = getComputedStyle(element)
    return Object.fromEntries([
      'border-top-style', 'border-top-width', 'border-top-color', 'border-radius',
      'background-color', 'color', 'font-size', 'line-height', 'padding-block', 'padding-inline',
    ].map((name) => [name, style.getPropertyValue(name)]))
  })
}

async function frame(pill: Locator) {
  return pill.evaluate((element) => {
    const { width, height } = element.getBoundingClientRect()
    return { width, height, background: getComputedStyle(element).backgroundColor }
  })
}

for (const [locale, direction] of [['en-US', 'ltr'], ['ar-EG', 'rtl']] as const) {
  test.describe(`shared tag pills in ${direction}`, () => {
    test.use({ locale })

    test('matches styles and edits inline while preserving filtering and rename scopes', async ({ page }, info) => {
      const tag = `shared-${direction}-${info.project.name}`
      const title = `Tag pills ${direction} ${info.project.name}`
      const made = await api('items', [title, `${title} sibling`].map((name) => ({
        itemType: 'book', title: name, tags: [{ tag, type: 1 }],
      })))
      expect(made.failed).toEqual({})
      const first = made.successful['0'].key
      const second = made.successful['1'].key
      await signIn(page)
      await page.locator('.library__row').filter({ hasText: title }).filter({ hasNotText: 'sibling' }).click()
      const global = page.locator(`.library__tag[data-tag-name="${tag}"]`)
      const detail = page.locator(`.tags__tag[data-tag-name="${tag}"]`)
      await expect(global.locator('.tag-pill__count')).toHaveText('2')
      await expect(detail.locator('.tag-pill__count')).toHaveCount(0)
      for (const scheme of ['light', 'dark'] as const) {
        await page.emulateMedia({ colorScheme: scheme })
        await expect(page.locator('html')).toHaveAttribute('data-theme', scheme)
        await page.mouse.move(0, 0)
        await expect.poll(() => appearance(detail)).toEqual(await appearance(global))
        expect((await appearance(detail))['border-top-style']).toBe('solid')
        await global.hover()
        const hovered = await appearance(global)
        await detail.hover()
        expect(await appearance(detail)).toEqual(hovered)
        expect(await accessibilityProblems(page)).toEqual([])
        for (const selected of [false, true]) {
          if (selected) await global.locator('.tag-pill__name').click()
          await global.hover()
          const closed = await frame(global)
          await global.locator('.tag-pill__edit').click()
          await expect(global.locator('.tag-pill__hint')).toHaveCount(0)
          expect(await frame(global)).toEqual(closed)
          await global.locator('input').fill('A much longer draft that must scroll inside the existing name space')
          expect(await frame(global)).toEqual(closed)
          await global.locator('input').fill('')
          await global.locator('input').press('Enter')
          await expect(global.locator('.tag-pill__error')).toBeVisible()
          expect(await frame(global)).toEqual(closed)
          await global.locator('input').press('Escape')
          if (selected) await global.locator('.tag-pill__name').click()
        }
      }
      await page.screenshot({ path: info.outputPath('tag-pills.png'), fullPage: true })

      // Only the global name is a filter; the item's name stays passive.
      await expect(detail.locator('.tag-pill__name')).not.toHaveAttribute('type', 'button')
      await detail.locator('.tag-pill__name').click()
      await expect(detail.locator('input')).toHaveCount(0)
      const filter = global.locator('button').first()
      await filter.click()
      await expect(filter).toHaveAttribute('aria-pressed', 'true')
      await filter.click()
      await expect(filter).toHaveAttribute('aria-pressed', 'false')

      await detail.locator('.tag-pill__edit').click()
      await expect(page.locator('dialog[open]')).toHaveCount(0)
      const localName = `${tag}-local`
      await detail.locator('input').fill(localName)
      await detail.locator('input').press('Enter')
      await expect.poll(async () => (await api(`items/${first}`)).data.tags).toEqual([{ tag: localName }])
      expect((await api(`items/${second}`)).data.tags).toEqual([{ tag, type: 1 }])

      const renamed = page.locator(`.tags__tag[data-tag-name="${localName}"]`)
      await expect(renamed.locator('.tag-pill__edit')).toBeFocused()
      await renamed.locator('.tag-pill__edit').click()
      await renamed.locator('input').fill('cancel this draft')
      await renamed.locator('input').press('Escape')
      await expect(renamed.locator('input')).toHaveCount(0)
      expect((await api(`items/${first}`)).data.tags).toEqual([{ tag: localName }])

      await global.locator('.tag-pill__edit').click()
      await expect(page.locator('dialog[open]')).toHaveCount(0)
      await expect(global.locator('input')).toBeFocused()
      await expect(global.locator('.tag-pill__count')).toHaveText('1')
      await expect(global.locator('.tag-pill__hint')).toHaveCount(0)
      const globalName = `${tag}-global`
      await global.locator('input').fill(globalName)
      await page.locator('.library__list h1').click()
      await expect.poll(async () => (await api(`items/${second}`)).data.tags).toEqual([{ tag: globalName }])
      expect((await api(`items/${first}`)).data.tags).toEqual([{ tag: localName }])

      // The cross removes this item's membership without changing its sibling.
      await renamed.locator('.tag-pill__remove').click()
      await expect.poll(async () => (await api(`items/${first}`)).data.tags).toEqual([])
      expect((await api(`items/${second}`)).data.tags).toEqual([{ tag: globalName }])
      await page.reload()
      await page.locator('.library__row').filter({ hasText: title }).filter({ hasNotText: 'sibling' }).click()
      await expect(page.locator('.tags__tag')).toHaveCount(0)

      // Desktop-assigned tag colors are displayed identically in both places.
      await page.locator('.library__row').filter({ hasText: 'Notes on the Analytical Engine' }).click()
      const globalColor = page.locator('.library__tag').filter({ hasText: 'computing' }).locator('.tag-pill__swatch')
      const detailColor = page.locator('.tags__tag--colored .tag-pill__swatch')
      await expect(globalColor).toHaveCSS('background-color', 'rgb(95, 178, 54)')
      await expect(detailColor).toHaveCSS('background-color', 'rgb(95, 178, 54)')
    })
  })
}
