import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

for (const [direction, locale] of [['ltr', 'en-US'], ['rtl', 'ar-EG']] as const) {
  test.describe(`${direction} editing confirmations`, () => {
    test.use({ locale })

    test('keeps confirmation controls and extensions readable and persists edits', async ({ page, request }, info) => {
      const title = `Editing confirmations ${direction} ${info.project.name}`
      const headers = { 'Zotero-API-Key': state().key }
      const made = await request.post('/users/1/items', { headers, data: [{ itemType: 'book', title, edition: '2' }] })
      expect(made.ok()).toBe(true)
      const body = await made.json()
      expect(body.failed).toEqual({})
      const key = body.successful['0'].key as string
      const stored = async () => (await (await request.get(`/users/1/items/${key}`, { headers })).json()).data
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('dir', direction)
      await page.locator('.library__search > button').click()
      const query = `"${title}"`
      const filtered = page.waitForResponse((response) => {
        const url = new URL(response.url())
        return url.pathname === '/web/libraries/1/items' && url.searchParams.get('q') === query
      })
      await page.locator('.library__search-field').fill(query)
      await filtered
      await expect(page.locator('.library__items [data-row]')).toHaveCount(1)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(page.viewportSize()!.width)
      await openItem(page, title)
      await page.locator('.info__type').selectOption('journalArticle')
      const typeDialog = page.getByRole('alertdialog')
      expect((await stored()).itemType).toBe('book')
      expect(await accessibilityProblems(page)).toEqual([])
      await page.screenshot({ path: info.outputPath(`${direction}-type.png`), fullPage: true })
      await typeDialog.getByRole('button').last().click()
      await expect.poll(async () => (await stored()).itemType).toBe('journalArticle')
      expect((await stored()).edition).toBeUndefined()

      const attach = page.locator('.detail__add-menu > button').first()
      await attach.scrollIntoViewIfNeeded()
      await expect(async () => {
        if ((await attach.getAttribute('aria-expanded')) !== 'true') await attach.click()
        await expect(page.getByRole('menu')).toBeVisible({ timeout: 500 })
      }).toPass()
      const bytes = Buffer.from(`%PDF-1.7\n${title}\n`)
      const chooser = page.waitForEvent('filechooser')
      await page.getByRole('menuitem').first().click()
      await (await chooser).setFiles({ name: 'paper.pdf', mimeType: 'application/pdf', buffer: bytes })
      await page.locator('.detail__children').getByText('PDF', { exact: true }).click()
      await page.locator('.info__value[aria-labelledby$="-filename"]').click()
      await page.keyboard.press('ControlOrMeta+a')
      await page.keyboard.type('paper.txt')
      await page.keyboard.press('Enter')
      const rename = page.getByRole('alertdialog')
      await expect(rename.locator('bdi[dir=ltr]').filter({ hasText: '.pdf' }).first()).toBeVisible()
      await expect(rename.locator('bdi[dir=ltr]').filter({ hasText: '.txt' }).first()).toBeVisible()
      const reversedExtensions = await rename.evaluate(element => {
        const reversed: string[] = []
        const texts = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
        while (texts.nextNode()) {
          const node = texts.currentNode
          for (const match of (node.textContent ?? '').matchAll(/\.(?:pdf|txt)/g)) {
            const range = document.createRange()
            range.setStart(node, match.index)
            range.setEnd(node, match.index + 1)
            const dot = range.getBoundingClientRect()
            range.setStart(node, match.index + 1)
            range.setEnd(node, match.index + 2)
            const firstLetter = range.getBoundingClientRect()
            if (dot.left >= firstLetter.left) reversed.push(match[0])
          }
        }
        return reversed
      })
      expect(reversedExtensions, 'Each extension displays its dot before its letters').toEqual([])
      await page.screenshot({ path: info.outputPath(`${direction}-extension.png`), fullPage: true })
      const splitWords = await rename.locator('.app-button__label').evaluateAll(labels => labels.flatMap(label => {
        const broken: string[] = []
        const texts = document.createTreeWalker(label, NodeFilter.SHOW_TEXT)
        while (texts.nextNode()) {
          const node = texts.currentNode
          for (const match of (node.textContent ?? '').matchAll(/\S+/gu)) {
            const range = document.createRange()
            range.setStart(node, match.index)
            range.setEnd(node, match.index + match[0].length)
            const lines = new Set([...range.getClientRects()].filter(r => r.width > 0).map(r => Math.round(r.top)))
            if (lines.size > 1) broken.push(match[0])
          }
        }
        return broken
      }))
      expect(splitWords, 'Confirmation buttons keep whole words on a line').toEqual([])
      const bounds = (await rename.boundingBox())!
      for (const button of await rename.getByRole('button').all()) {
        const box = (await button.boundingBox())!
        expect(box.x).toBeGreaterThanOrEqual(bounds.x)
        expect(box.x + box.width).toBeLessThanOrEqual(bounds.x + bounds.width)
      }
      expect(await accessibilityProblems(page)).toEqual([])
      await rename.getByRole('button').last().click()
      const children = async () => (await (await request.get(`/users/1/items/${key}/children`, { headers })).json())
      await expect.poll(async () => (await children())[0].data.filename).toBe('paper.txt')
      const [file] = await children()
      const download = await request.get(`/users/1/items/${file.key}/file`, { headers })
      expect(download.ok()).toBe(true)
      expect(download.headers()['content-disposition']).toContain('paper.txt')
      expect(await download.body()).toEqual(bytes)
    })
  })
}
