import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

const labels = {
  'en-US': {
    type: 'Change Item Type', typeQuestion: 'Are you sure you want to change the item type?', change: 'Change',
    attach: 'Add Attachment', file: 'Attach File…', filename: 'Filename', use: 'Use .txt',
    extensionQuestion: 'Are you sure you want to change the file extension from “.pdf” to “.txt”?',
    extensionWarning: 'If you change the extension, the file may open in a different application.',
  },
  af: {
    type: 'Verander itemtipe', typeQuestion: 'Is u seker u wil die itemtipe verander?', change: 'Verander',
    attach: 'Voeg aanhegsel by', file: 'Heg lêer aan…', filename: 'Lêernaam', use: 'Gebruik .txt',
    extensionQuestion: 'Is u seker u wil die lêeruitbreiding van “.pdf” na “.txt” verander?',
    extensionWarning: 'As u die uitbreiding verander, kan die lêer in ’n ander toepassing oopmaak.',
  },
  fi: {
    type: 'Vaihda nimikkeen tyyppi', typeQuestion: 'Haluatko varmasti vaihtaa nimikkeen tyypin?', change: 'Muuta',
    attach: 'Lisää liite', file: 'Liitä tiedosto…', filename: 'Tiedostonimi', use: 'Käytä .txt',
    extensionQuestion: 'Haluatko varmasti muuttaa tiedostopäätteen “.pdf” muotoon “.txt”?',
    extensionWarning: 'Jos vaihdat tiedostopäätteen, tiedosto saattaa avautua eri sovelluksessa.',
  },
  ar: {
    type: 'تغيير نوع العنصر', typeQuestion: 'هل تريد بالتأكيد تغيير نوع العنصر؟', change: 'تغيير',
    attach: 'إضافة مرفق', file: 'إرفاق ملف…', filename: 'اسم الملف', use: 'استخدام .txt',
    extensionQuestion: 'هل تريد بالتأكيد تغيير امتداد الملف من «.pdf» إلى «.txt»؟',
    extensionWarning: 'إذا غيرت الامتداد فقد يُفتح الملف في تطبيق مختلف.',
  },
}

for (const [tag, translated] of Object.entries(labels)) {
  test.describe(`editing confirmations in ${tag}`, () => {
    test.use({ locale: tag })

    test('keeps translated editing choices readable and saves the choices made', async ({ page, request }, info) => {
      const title = `Editing confirmations ${tag} ${info.project.name}`
      const headers = { 'Zotero-API-Key': state().key }
      const made = await request.post('/users/1/items', { headers, data: [{ itemType: 'book', title, edition: '2' }] })
      expect(made.ok()).toBe(true)
      const body = await made.json()
      expect(body.failed).toEqual({})
      const key = body.successful['0'].key as string
      const stored = async () => (await (await request.get(`/users/1/items/${key}`, { headers })).json()).data
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await openItem(page, title)
      await page.locator('.info__type').selectOption('journalArticle')
      const typeDialog = page.getByRole('alertdialog', { name: translated.type, exact: true })
      await expect(typeDialog).toContainText(translated.typeQuestion)
      expect((await stored()).itemType).toBe('book')
      expect(await accessibilityProblems(page)).toEqual([])
      await page.screenshot({ path: info.outputPath(`${tag}-type.png`), fullPage: true })
      await typeDialog.getByRole('button', { name: translated.change, exact: true }).click()
      await expect.poll(async () => (await stored()).itemType).toBe('journalArticle')
      expect((await stored()).edition).toBeUndefined()

      const attach = page.locator('.detail').getByRole('button', { name: translated.attach, exact: true })
      await attach.scrollIntoViewIfNeeded()
      await expect(async () => {
        if ((await attach.getAttribute('aria-expanded')) !== 'true') await attach.click()
        await expect(page.getByRole('menu', { name: translated.attach })).toBeVisible({ timeout: 500 })
      }).toPass()
      const bytes = Buffer.from(`%PDF-1.7\n${title}\n`)
      const chooser = page.waitForEvent('filechooser')
      await page.getByRole('menuitem', { name: translated.file, exact: true }).click()
      await (await chooser).setFiles({ name: 'paper.pdf', mimeType: 'application/pdf', buffer: bytes })
      await page.locator('.detail__children').getByText('PDF', { exact: true }).click()
      await page.getByRole('button', { name: translated.filename, exact: true }).click()
      await page.keyboard.press('ControlOrMeta+a')
      await page.keyboard.type('paper.txt')
      await page.keyboard.press('Enter')
      const rename = page.getByRole('alertdialog', { name: translated.filename, exact: true })
      await expect(rename).toContainText(translated.extensionQuestion)
      await expect(rename).toContainText(translated.extensionWarning)
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
      await page.screenshot({ path: info.outputPath(`${tag}-extension.png`), fullPage: true })
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
      await rename.getByRole('button', { name: translated.use, exact: true }).click()
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
