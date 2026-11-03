import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

for (const [locale, direction] of [['en-US', 'ltr'], ['ar-EG', 'rtl']] as const) {
  test.describe(`child detail navigation in ${direction}`, () => {
    test.use({ locale })

    test('returns to the edited parent after closing a note or attachment', async ({ page, request }, info) => {
      const headers = { 'Zotero-API-Key': state().key }
      const title = `Detail navigation ${direction} ${info.project.name}`
      const made = await request.post('/users/1/items', { headers, data: [{ itemType: 'book', title }] })
      expect(made.ok()).toBe(true)
      const parent = (await made.json()).successful['0'].key
      const noteText = `${title} note`
      const attachmentTitle = `${title} attachment`
      const children = await request.post('/users/1/items', { headers, data: [
        { itemType: 'note', parentItem: parent, note: `<p>${noteText}</p>` },
        { itemType: 'attachment', parentItem: parent, linkMode: 'linked_url', title: attachmentTitle, url: 'https://example.org/' },
      ] })
      expect(children.ok()).toBe(true)
      const body = await children.json()
      expect(body.failed).toEqual({})
      const note = body.successful['0'].key
      const attachment = body.successful['1'].key
      const read = async (key: string) => (await (await request.get(`/users/1/items/${key}`, { headers })).json()).data
      try {
        await signIn(page)
        await openItem(page, title)
        const titleField = page.locator('.detail .info__value[aria-labelledby$="-title"]')
        await titleField.click()
        await page.locator('.detail textarea[aria-labelledby$="-title"]').fill(`${title} edited`)
        await page.locator('.detail textarea[aria-labelledby$="-title"]').press('Enter')
        await expect.poll(async () => (await read(parent)).title).toBe(`${title} edited`)

        await page.locator('.detail__child').filter({ hasText: noteText }).click()
        await expect(page.locator('.detail__title')).toHaveText(noteText)
        await page.locator('.note-editor .ProseMirror').fill(`${noteText} edited`)
        await expect.poll(async () => (await read(note)).note).toContain(`${noteText} edited`)
        await page.locator('.detail__close').click()
        await expect(page.locator('.detail__title')).toHaveText(`${title} edited`)
        await expect(page.locator('.detail__title')).toBeFocused()

        await page.locator('.detail__child').filter({ hasText: attachmentTitle }).click()
        await expect(page.locator('.detail__title')).toHaveText(attachmentTitle)
        await titleField.click()
        await page.locator('.detail textarea[aria-labelledby$="-title"]').fill(`${attachmentTitle} edited`)
        await page.locator('.detail textarea[aria-labelledby$="-title"]').press('Enter')
        await expect.poll(async () => (await read(attachment)).title).toBe(`${attachmentTitle} edited`)
        await page.locator('.detail__close').click()
        await expect(page.locator('.detail__title')).toHaveText(`${title} edited`)
        await expect(titleField).toHaveText(`${title} edited`)
        expect(await accessibilityProblems(page)).toEqual([])
        await page.locator('.library__detail').screenshot({ path: info.outputPath('returned-parent.png') })
        await page.locator('.detail__close').click()
        await expect(page.locator('.library__detail')).toHaveCount(0)
      } finally {
        const current = await request.get('/users/1/items?limit=1', { headers })
        const removed = await request.delete(`/users/1/items?itemKey=${parent},${note},${attachment}`, {
          headers: { ...headers, 'If-Unmodified-Since-Version': current.headers()['last-modified-version']! },
        })
        expect(removed.ok()).toBe(true)
      }
    })
  })
}
