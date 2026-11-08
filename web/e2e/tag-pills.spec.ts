import type { Locator, Page } from '@playwright/test'

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

async function taggedPair(page: Page, direction: string, project: string, suffix = '') {
  const tag = `shared-${direction}-${project}${suffix}`
  const title = `Tag pills${suffix} ${direction} ${project}`
  const made = await api('items', [title, `${title} sibling`].map((name) => ({
    itemType: 'book', title: name, tags: [{ tag, type: 1 }],
  })))
  expect(made.failed).toEqual({})
  await signIn(page)
  await page.locator('.library__row').filter({ hasText: title }).filter({ hasNotText: 'sibling' }).click()
  return {
    tag, title,
    first: made.successful['0'].key as string,
    second: made.successful['1'].key as string,
    global: page.locator(`.library__tag[data-tag-name="${tag}"]`),
    detail: page.locator(`.tags__tag[data-tag-name="${tag}"]`),
  }
}

for (const [locale, direction] of [['en-US', 'ltr'], ['ar-EG', 'rtl']] as const) {
  test.describe(`shared tag pills in ${direction}`, () => {
    test.use({ locale })

    test('orders global and item tags by color position, emoji and locale', async ({ page, request }, info) => {
      const suffix = `${direction}-${info.project.name}`
      const names = ['apple', 'a colored', 'éclair', 'reading 📚 z', 'Zebra', 'z urgent', 'reading 📚 a']
        .map((name) => `${name}-${suffix}`)
      const title = `Tag order ${suffix}`
      const made = await api('items', [{ itemType: 'book', title, tags: names.map((tag) => ({ tag })) }])
      expect(made.failed).toEqual({})
      const previous = await api('settings/tagColors')
      const headers = { 'Zotero-API-Key': state().key }
      try {
        const colored = await request.put('/users/1/settings/tagColors', { headers, data: { value: [
          { name: names[5], color: '#FF6666' },
          { name: names[1], color: '#5FB236' },
          ...previous.value,
        ] } })
        expect(colored.ok()).toBe(true)
        await signIn(page)
        await page.locator('.library__row').filter({ hasText: title }).click()
        const expected = [5, 1, 6, 3, 0, 2, 4].map((index) => names[index])
        const global = page.locator('.library__tag')
        await expect.poll(() => global.evaluateAll((pills, names) => pills
          .map((pill) => (pill as HTMLElement).dataset.tagName)
          .filter((name) => names.includes(name!)), names)).toEqual(expected)
        expect(await page.locator('.tags__tag').evaluateAll((pills) => pills
          .map((pill) => (pill as HTMLElement).dataset.tagName))).toEqual(expected)
        expect(await accessibilityProblems(page)).toEqual([])
        await page.screenshot({ path: info.outputPath('tag-order.png'), fullPage: true })
      } finally {
        const restored = await request.put('/users/1/settings/tagColors', { headers, data: { value: previous.value } })
        expect(restored.ok()).toBe(true)
      }
    })

    for (const scheme of ['light', 'dark'] as const) {
      test(`matches ${scheme} styles without resizing while editing`, async ({ page }, info) => {
        const { global, detail } = await taggedPair(page, direction, info.project.name, `-${scheme}`)
        await expect(global.locator('.tag-pill__count')).toHaveText('2')
        await expect(detail.locator('.tag-pill__count')).toHaveCount(0)
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
        await page.screenshot({ path: info.outputPath('tag-pills.png'), fullPage: true })
      })
    }

    test('edits inline while preserving filtering and rename scopes', async ({ page }, info) => {
      const { tag, title, first, second, global, detail } = await taggedPair(page, direction, info.project.name)
      await page.emulateMedia({ colorScheme: 'dark' })
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

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
