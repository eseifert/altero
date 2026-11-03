import type { Page } from '@playwright/test'

import { accessibilityProblems, expect, signIn, state, test } from './state'

interface Sample {
  phase: string
  height: string
  duration: number
  inactive: boolean
}

async function bookWithNote(name: string): Promise<string> {
  const { baseURL, key } = state()
  async function create(data: unknown) {
    const response = await fetch(`${baseURL}/users/1/items`, {
      method: 'POST',
      headers: { 'Zotero-API-Key': key, 'Content-Type': 'application/json' },
      body: JSON.stringify([data]),
    })
    expect(response.ok).toBeTruthy()
    const body = await response.json()
    expect(body.failed).toEqual({})
    return body.successful['0'].key as string
  }
  const parent = await create({ itemType: 'book', title: name })
  return create({ itemType: 'note', parentItem: parent, note: `<p>${name} child</p>` })
}

async function observe(page: Page, selector: string): Promise<void> {
  await page.evaluate((selector) => {
    const samples: Sample[] = []
    ;(window as unknown as { detailMotion: Sample[] }).detailMotion = samples
    new MutationObserver(() => {
      for (const element of document.querySelectorAll<HTMLElement>(selector)) {
        for (const phase of ['enter', 'leave']) {
          if (element.classList.contains(`collapse-${phase}-active`)) {
            samples.push({
              phase,
              height: element.style.height,
              duration: parseFloat(getComputedStyle(element).transitionDuration),
              inactive: element.hasAttribute('inert') && element.getAttribute('aria-hidden') === 'true',
            })
          }
        }
      }
    }).observe(document.body, {
      childList: true, attributes: true, subtree: true,
      attributeFilter: ['class', 'style', 'inert', 'aria-hidden'],
    })
  }, selector)
}

async function samples(page: Page): Promise<Sample[]> {
  return page.evaluate(() => (window as unknown as { detailMotion: Sample[] }).detailMotion)
}

for (const locale of ['en-US', 'ar-EG']) {
  for (const reducedMotion of ['no-preference', 'reduce'] as const) {
    test.describe(`detail motion ${locale} ${reducedMotion}`, () => {
      test.use({ locale, reducedMotion })

      test('optional sections close and reopen when changing between parent and child', async ({ page }, info) => {
        const name = `Sections ${locale} ${reducedMotion} ${info.project.name}`
        await bookWithNote(name)
        await signIn(page)
        const row = page.locator('.library__row').filter({ hasText: name })
        await row.click()
        await expect(page.locator('.detail__child').filter({ hasText: `${name} child` })).toBeVisible()
        await observe(page, '.detail__section')
        await page.locator('.detail__child').filter({ hasText: `${name} child` }).click()
        await expect(page.locator('.detail__title')).toHaveText(`${name} child`)
        await expect(page.locator('.detail__section')).toHaveCount(0)
        expect((await samples(page)).some((sample) => sample.phase === 'leave' && sample.inactive)).toBe(true)
        await row.click()
        await expect(page.locator('.detail__section')).toHaveCount(3)
        await expect.poll(async () => (await samples(page)).some((sample) => sample.phase === 'enter')).toBe(true)
        const recorded = await samples(page)
        expect(recorded.every((sample) => reducedMotion === 'reduce'
          ? sample.duration <= 0.001 : sample.duration >= 0.12 && sample.duration <= 0.25)).toBe(true)
        await expect.poll(() => page.locator('.detail__section').evaluateAll((elements) =>
          elements.every((element) => !(element as HTMLElement).style.height && !element.hasAttribute('inert')),
        )).toBe(true)
        expect(await accessibilityProblems(page)).toEqual([])
      })

      test('related search survives interrupted opening and returns keyboard focus on Escape', async ({ page }, info) => {
        const name = `Related motion ${locale} ${reducedMotion} ${info.project.name}`
        await bookWithNote(name)
        await signIn(page)
        await page.locator('.library__row').filter({ hasText: name }).click()
        const add = page.locator('.related__heading button')
        await expect(add).toBeVisible()
        await observe(page, '.related__search')
        await add.evaluate((button: HTMLButtonElement) => {
          button.click()
          requestAnimationFrame(() => requestAnimationFrame(() => {
            document.querySelector<HTMLButtonElement>('.related__search button')!.click()
          }))
        })
        await expect(page.locator('.related__search')).toHaveCount(0)
        await add.click()
        const field = page.locator('.related__input')
        await expect(field).toBeFocused()
        await expect.poll(() => page.locator('.related__search').evaluate((element) =>
          (element as HTMLElement).style.height,
        )).toBe('')
        expect((await samples(page)).some((sample) => sample.phase === 'enter')).toBe(true)
        await field.press('Escape')
        await expect(page.locator('.related__search')).toHaveCount(0)
        await expect(add).toBeFocused()
        expect(await accessibilityProblems(page)).toEqual([])
      })
    })
  }
}
