import type { Page } from '@playwright/test'

import { accessibilityProblems, expect, signIn, state, test } from './state'

async function api(path: string, body?: unknown) {
  const { baseURL, key } = state()
  const response = await fetch(`${baseURL}/users/1/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Zotero-API-Key': key, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  expect(response.ok).toBeTruthy()
  const result = await response.json()
  if (body !== undefined) expect(result.failed).toEqual({})
  return result
}

interface Sample {
  duration: number
  height: number
  opacity: number
  inactive: boolean
}

async function observe(page: Page): Promise<void> {
  await page.evaluate(() => {
    const samples: Sample[] = []
    const tracked = new WeakSet<HTMLElement>()
    ;(window as unknown as { rowMotion: Sample[] }).rowMotion = samples
    function sample(element: HTMLElement): void {
      if (element.isConnected && element.classList.contains('item-row-leave-active')) {
        samples.push({
          duration: parseFloat(getComputedStyle(element).transitionDuration),
          height: element.getBoundingClientRect().height,
          opacity: parseFloat(getComputedStyle(element).opacity),
          inactive: element.hasAttribute('inert') && element.getAttribute('aria-hidden') === 'true',
        })
        requestAnimationFrame(() => sample(element))
      }
    }
    new MutationObserver(() => {
      for (const element of document.querySelectorAll<HTMLElement>('.item-row-leave-active')) {
        if (tracked.has(element)) continue
        tracked.add(element)
        sample(element)
      }
    }).observe(document.body, {
      childList: true, attributes: true, subtree: true,
      attributeFilter: ['class', 'style', 'inert', 'aria-hidden'],
    })
  })
}

async function checkMotion(page: Page, reduced: boolean): Promise<void> {
  const samples = await page.evaluate(() => (window as unknown as { rowMotion: Sample[] }).rowMotion)
  expect(samples.length).toBeGreaterThan(0)
  expect(samples.every((sample) => sample.inactive)).toBe(true)
  expect(samples.every((sample) => reduced
    ? sample.duration <= 0.001 : sample.duration >= 0.12 && sample.duration <= 0.25)).toBe(true)
  expect(samples.some((sample) => sample.height > 0)).toBe(true)
  if (!reduced) expect(samples.some((sample) => sample.opacity < 1)).toBe(true)
}

for (const locale of ['en-US', 'ar-EG']) {
  for (const reducedMotion of ['no-preference', 'reduce'] as const) {
    test.describe(`row motion ${locale} ${reducedMotion}`, () => {
      test.use({ locale, reducedMotion })

      test('trash keeps keyboard focus and filing animates the last row into an empty view', async ({ page }, info) => {
        const name = `Rows ${locale} ${reducedMotion} ${info.project.name}`
        const collections = await api('collections', [{ name }, { name: `${name} destination` }])
        const source = collections.successful['0'].key as string
        const target = collections.successful['1'].key as string
        const made = await api('items', [
          { itemType: 'book', title: `${name} first`, collections: [source] },
          { itemType: 'book', title: `${name} second`, collections: [source] },
        ])
        const first = made.successful['0'].key as string
        const second = made.successful['1'].key as string
        await signIn(page)
        await page.locator(`[data-drop="collection:${source}"] .tree__name`).click()
        await expect(page.locator('.library__items [data-row]')).toHaveCount(2)
        await observe(page)
        const firstRow = page.locator(`[data-row="${first}"]`)
        const secondRow = page.locator(`[data-row="${second}"]`)
        await firstRow.focus()
        await firstRow.press('Delete')
        await expect(firstRow).toHaveCount(0)
        await checkMotion(page, reducedMotion === 'reduce')
        await expect(secondRow).toBeFocused()
        await secondRow.press('Delete')
        await expect(secondRow).toHaveCount(0)
        await expect(page.locator('.library__heading')).toBeFocused()
        await expect(page.locator('.library__table > .library__state')).toBeVisible()

        await page.locator('.toast__action').last().click()
        await expect(secondRow).toBeVisible()
        await secondRow.click()
        await page.locator('.detail__tools button').first().click()
        const dialog = page.getByRole('dialog')
        await dialog.getByRole('combobox').selectOption(`place:${target}`)
        await dialog.getByRole('checkbox').check()
        await dialog.locator('button[type="submit"]').click()
        await expect(secondRow).toHaveCount(0)
        await expect(page.locator('.library__table > .library__state')).toBeVisible()
        await page.locator(`[data-drop="collection:${target}"] .tree__name`).click()
        await expect(secondRow).toBeVisible()
        expect((await api(`items/${second}`)).data.collections).toEqual([target])
        expect((await api(`items/${first}`)).data.deleted).toBe(1)
        expect(await accessibilityProblems(page)).toEqual([])
      })

      test('a disappearing duplicate group animates through the empty result and releases focus', async ({ page }, info) => {
        const name = `Duplicate rows ${locale} ${reducedMotion} ${info.project.name}`
        const DOI = `10.1234/${name.replaceAll(' ', '-')}`
        await api('items', [
          { itemType: 'journalArticle', title: name, DOI },
          { itemType: 'journalArticle', title: name, DOI },
        ])
        await signIn(page)
        await page.locator('[data-drop="publications:"] + .library__scope-row > button').click()
        await page.locator('.library__search > button').click()
        const filtered = page.waitForResponse((response) => {
          const url = new URL(response.url())
          return url.pathname === '/web/libraries/1/items' && url.searchParams.get('q') === name
        })
        await page.locator('.library__search-field').fill(name)
        await filtered
        const rows = page.locator('.duplicate-group__row')
        await expect(rows).toHaveCount(2)
        await observe(page)
        await rows.first().focus()
        await rows.first().press('Delete')
        await expect(rows).toHaveCount(0)
        await checkMotion(page, reducedMotion === 'reduce')
        await expect(page.locator('.library__heading')).toBeFocused()
        await expect(page.locator('.library__table > .library__state')).toBeVisible()
        expect(await accessibilityProblems(page)).toEqual([])
      })
    })
  }
}
