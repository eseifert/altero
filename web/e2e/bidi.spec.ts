import type { APIRequestContext, Locator } from '@playwright/test'

import { accessibilityProblems, expect, signIn, state, test } from './state'

async function seed(request: APIRequestContext, suffix: string) {
  const headers = { 'Zotero-API-Key': state().key }
  const collectionResponse = await request.post('/users/1/collections', {
    headers, data: [{ name: `مجموعة (${suffix})` }],
  })
  expect(collectionResponse.ok()).toBe(true)
  const collection = (await collectionResponse.json()).successful['0'].key as string
  const title = `دراسة (2026) — ${suffix}`
  const english = `English study (2026) — ${suffix}`
  const response = await request.post('/users/1/items', { headers, data: [
    { itemType: 'book', title, collections: [collection], inPublications: true,
      creators: [{ creatorType: 'author', name: 'שלום (123)' }],
      tags: [{ tag: 'پژوهش ۱۲۳' }], publisher: 'ناشر (2026)', abstractNote: 'العربية (123)' },
    { itemType: 'book', title: english, collections: [collection] },
  ] })
  expect(response.ok()).toBe(true)
  const body = await response.json()
  expect(body.failed).toEqual({})
  const book = body.successful['0'].key as string
  const other = body.successful['1'].key as string
  const children = await request.post('/users/1/items', { headers, data: [
    { itemType: 'note', parentItem: book, inPublications: true,
      note: '<p>العربية (123)</p><p>English (123)</p><p dir="rtl">Forced English (123)</p>' },
    { itemType: 'attachment', linkMode: 'linked_url', parentItem: book, inPublications: true,
      title: 'مرفق (123)', url: 'https://example.org/reading' },
  ] })
  expect(children.ok()).toBe(true)
  const childBody = await children.json()
  expect(childBody.failed).toEqual({})
  return { book, other, note: childBody.successful['0'].key as string, collection, title, english }
}

async function direction(element: Locator, expected: 'ltr' | 'rtl') {
  await expect(element).toHaveAttribute('dir', 'auto')
  await expect(element).toHaveCSS('direction', expected)
}

for (const [ui, locale] of [['ltr', 'en-US'], ['rtl', 'ar-EG']] as const) {
  test.describe(`${ui} interface with mixed content`, () => {
    test.use({ locale })

    test('reads and edits library text in its own direction', async ({ page, request }, info) => {
      const data = await seed(request, `library-${ui}-${info.project.name}`)
      await signIn(page)
      const collection = page.locator(`[data-drop="collection:${data.collection}"]`)
      await direction(collection.locator('.tree__label'), 'rtl')
      await collection.locator('.tree__name').click()
      const row = page.locator(`[data-row="${data.book}"]`)
      await direction(row.locator('.library__cell--title'), 'rtl')
      await direction(row.locator('.library__cell').nth(2), 'rtl')
      await direction(page.locator(`[data-row="${data.other}"] .library__cell--title`), 'ltr')
      await expect(row).toHaveCSS('direction', ui)
      await row.click()
      const field = page.locator(`.info__value[aria-labelledby="info-${data.book}-publisher"]`)
      await direction(field, 'rtl')
      await field.click()
      const input = page.locator('.info__input')
      await direction(input, 'rtl')
      await input.fill('English publisher (2026)')
      await direction(input, 'ltr')
      await input.press('Enter')
      await expect(field).toHaveText('English publisher (2026)')
      await direction(field, 'ltr')
      await direction(page.locator('.tags__name').filter({ hasText: 'پژوهش ۱۲۳' }), 'rtl')
      await page.screenshot({ path: info.outputPath(`${ui}-item.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])

      await page.locator('.detail__child').filter({ hasText: 'العربية (123)' }).click()
      const editor = page.locator('.ProseMirror')
      await expect(editor).toBeVisible()
      await direction(editor.locator('p').nth(0), 'rtl')
      await direction(editor.locator('p').nth(1), 'ltr')
      await expect(editor.locator('p').nth(2)).toHaveCSS('direction', 'rtl')
      await page.screenshot({ path: info.outputPath(`${ui}-note.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
      // Merely opening mixed-direction notes must not rewrite synced data.
      const stored = await request.get(`/users/1/items/${data.note}`, {
        headers: { 'Zotero-API-Key': state().key },
      })
      expect((await stored.json()).data.note).toBe(
        '<p>العربية (123)</p><p>English (123)</p><p dir="rtl">Forced English (123)</p>',
      )
    })

    test('keeps shared and published text independent of the UI', async ({ page, request }, info) => {
      const data = await seed(request, `public-${ui}-${info.project.name}`)
      await signIn(page)
      const url = await page.evaluate(async (collection) => {
        const csrf = decodeURIComponent(document.cookie.split('; ').find(c => c.startsWith('altero_csrf='))!.split('=')[1]!)
        const response = await fetch(`/web/libraries/1/collections/${collection}/shares`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
          body: JSON.stringify({ subcollections: true, files: false }),
        })
        if (!response.ok) throw new Error(`Share failed: ${response.status}`)
        return (await response.json()).url as string
      }, data.collection)

      for (const [path, prefix] of [[url, 'entry'], ['/app/u/ada', 'publication']] as const) {
        await page.goto(path)
        const entry = page.locator(`.${prefix}`).filter({ has: page.locator(`.${prefix}__title`, { hasText: data.title }) })
        await direction(entry.locator(`.${prefix}__title`), 'rtl')
        await direction(entry.locator(`.${prefix}__byline > span`).first(), 'rtl')
        await entry.locator(`.${prefix}__summary`).click()
        await direction(entry.locator(`.${prefix}__abstract`), 'rtl')
        const publisher = entry.locator(`.${prefix}__fields dd`).filter({ hasText: 'ناشر (2026)' })
        await direction(publisher, 'rtl')
        const note = entry.locator(prefix === 'entry' ? '.entry__note-body' : '.publication__note')
        await direction(note.locator('p').nth(0), 'rtl')
        await direction(note.locator('p').nth(1), 'ltr')
        await expect(note.locator('p').nth(2)).toHaveCSS('direction', 'rtl')
        await expect(page.locator('html')).toHaveAttribute('dir', ui)
        await page.screenshot({ path: info.outputPath(`${ui}-${prefix}.png`), fullPage: true })
        expect(await accessibilityProblems(page)).toEqual([])
      }
    })
  })
}
