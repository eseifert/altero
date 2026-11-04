import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

for (const locale of ['en-US', 'ar-EG']) {
  test.describe(`optimistic tags in ${locale}`, () => {
    test.use({ locale })

    test('shows queued chips before saving and restores only refused changes', async ({ page, request }, info) => {
      const headers = { 'Zotero-API-Key': state().key }
      const title = `Tag feedback ${locale} ${info.project.name}`
      const made = await request.post('/users/1/items', { headers, data: [{ itemType: 'book', title, tags: [] }] })
      expect(made.ok()).toBe(true)
      const key = (await made.json()).successful['0'].key as string
      const endpoint = `/web/libraries/1/items/${key}`
      const storedTags = async () => {
        const response = await request.get(`/users/1/items/${key}`, { headers })
        expect(response.ok()).toBe(true)
        return (await response.json()).data.tags
      }
      let release = () => {}
      let writes = 0
      try {
        await signIn(page)
        await openItem(page, title)
        const tags = page.locator('.detail .tags')
        const names = tags.locator('.tag-pill__name')
        const list = tags.locator('.tags__list')
        const held = new Promise<void>((resolve) => { release = resolve })
        await page.route(`**${endpoint}`, async (route) => {
          if (route.request().method() !== 'PATCH') return route.continue()
          writes += 1
          if (writes === 1) {
            await held
            await route.fulfill({ status: 403, json: { message: 'Tag refused' } })
          } else await route.continue()
        })
        await tags.locator('.tags__heading button').click()
        const input = tags.getByRole('combobox')
        for (const name of ['first', 'second']) {
          await input.fill(name)
          await input.press('Enter')
        }
        await expect(names).toHaveText(['first', 'second'])
        await expect(list).toHaveAttribute('aria-busy', 'true')
        expect(writes).toBe(1)
        expect(await storedTags()).toEqual([])
        expect(await accessibilityProblems(page)).toEqual([])
        await page.screenshot({ path: info.outputPath('pending-tags.png') })
        release()
        await expect(tags.getByRole('alert')).toHaveText('Tag refused')
        await expect(names).toHaveText(['second'])
        await expect(list).toHaveAttribute('aria-busy', 'false')
        expect(await storedTags()).toEqual([{ tag: 'second' }])

        // A refused removal restores its chip; a real removal survives reload.
        await page.unroute(`**${endpoint}`)
        let removeRelease = () => {}
        const removing = new Promise<void>((resolve) => { removeRelease = resolve })
        release = removeRelease
        await page.route(`**${endpoint}`, async (route) => {
          if (route.request().method() !== 'PATCH') return route.continue()
          await removing
          await route.fulfill({ status: 403, json: { message: 'Removal refused' } })
        })
        await tags.locator('.tag-pill__remove').click()
        await expect(names).toHaveCount(0)
        await expect(list).toHaveAttribute('aria-busy', 'true')
        expect(await storedTags()).toEqual([{ tag: 'second' }])
        release()
        await expect(names).toHaveText(['second'])
        await expect(tags.getByRole('alert')).toHaveText('Removal refused')
        await page.unroute(`**${endpoint}`)
        await tags.locator('.tag-pill__remove').click()
        await expect(tags.locator('[aria-busy="true"]')).toHaveCount(0)
        await expect(names).toHaveCount(0)
        expect(await storedTags()).toEqual([])
        await page.reload()
        await openItem(page, title)
        await expect(names).toHaveCount(0)
        expect(await accessibilityProblems(page)).toEqual([])
      } finally {
        release()
        await page.unrouteAll({ behavior: 'ignoreErrors' })
        const current = await request.get(`/users/1/items/${key}`, { headers })
        const removed = await request.delete(`/users/1/items/${key}`, {
          headers: { ...headers, 'If-Unmodified-Since-Version': current.headers()['last-modified-version']! },
        })
        expect(removed.ok()).toBe(true)
      }
    })
  })
}
