import { accessibilityProblems, expect, signIn, state, test } from './state'

/* Both projects run against the one seeded library, so every note written
   here says which project wrote it. */

const headers = () => ({ 'Zotero-API-Key': state().key, 'Content-Type': 'application/json' })

/** The note's HTML as the server stores it, which is what a desktop syncs. */
async function stored(text: string): Promise<{ key: string; version: number; note: string; parentItem?: string }> {
  const { baseURL } = state()
  const found = await fetch(`${baseURL}/users/1/items?itemType=note&q=${encodeURIComponent(text)}`, {
    headers: headers(),
  })
  const [item] = (await found.json()) as [{ key: string; version: number; data: { note: string; parentItem?: string } }]
  return { key: item.key, version: item.version, note: item.data.note, parentItem: item.data.parentItem }
}

/** A standalone note made the way a desktop would make it. */
async function seedNote(html: string): Promise<void> {
  const { baseURL } = state()
  const made = await fetch(`${baseURL}/users/1/items`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify([{ itemType: 'note', note: html, tags: [], collections: [], relations: {} }]),
  })
  expect(made.status).toBe(200)
}

test('a note is opened in the editor without the script somebody put in it', async ({ page }) => {
  await signIn(page)
  await page.getByText('Notes on the Analytical Engine').first().click()
  await page.getByText('The engine weaves algebraic patterns.').first().click()

  const text = page.locator('.note-editor .ProseMirror')
  await expect(text).toContainText('algebraic patterns')
  expect(await text.innerHTML()).not.toMatch(/onerror/i)
  expect(await page.evaluate(() => (window as unknown as { __ran?: number }).__ran)).toBeUndefined()
})

test('what is typed in a note is saved as the desktop writes it, and is there after a reload', async ({ page }, testInfo) => {
  const marker = `typed-${testInfo.project.name}`
  await seedNote(`<div data-schema-version="9"><p>Draft ${marker}</p>\n</div>`)
  await signIn(page)
  await page.getByText(`Draft ${marker}`).first().click()

  const text = page.locator('.note-editor .ProseMirror')
  await text.click()
  await page.keyboard.press('End')
  await page.keyboard.type(' and more')
  await page.keyboard.press('Enter')
  await page.keyboard.press('ControlOrMeta+b')
  await page.keyboard.type('bold')
  await expect(page.locator('.note-pane__state')).toHaveText('Saved.')

  expect((await stored(marker)).note).toBe(
    `<div data-schema-version="9"><p>Draft ${marker} and more</p>\n<p><strong>bold</strong></p>\n</div>`,
  )

  await page.reload()
  await page.getByText(`Draft ${marker} and more`).first().click()
  await expect(page.locator('.note-editor .ProseMirror strong')).toHaveText('bold')
})

test('the toolbar turns a line into a heading', async ({ page }, testInfo) => {
  const marker = `heading-${testInfo.project.name}`
  await seedNote(`<p>Heading ${marker}</p>`)
  await signIn(page)
  await page.getByText(`Heading ${marker}`).first().click()

  await page.locator('.note-editor .ProseMirror').click()
  await page.getByRole('button', { name: 'Format Text' }).click()
  // Seen where it is drawn, and not clipped by the toolbar it opens from,
  // which scrolls sideways: the entry is what is under its own centre.
  const quote = page.getByRole('menuitemradio', { name: 'Block Quote' })
  const box = (await quote.boundingBox())!
  expect(
    await page.evaluate(
      ([x, y]) => document.elementFromPoint(x!, y!)?.closest('[role="menuitemradio"]')?.textContent?.trim(),
      [box.x + box.width / 2, box.y + box.height / 2],
    ),
  ).toBe('Block Quote')
  await page.getByRole('menuitemradio', { name: 'Heading 1' }).click()
  await expect(page.locator('.note-editor .ProseMirror h1')).toHaveText(`Heading ${marker}`)
  await expect(page.locator('.note-pane__state')).toHaveText('Saved.')
  expect((await stored(marker)).note).toContain(`<h1>Heading ${marker}</h1>`)
})

test('a note opened and left is not written', async ({ page }, testInfo) => {
  const marker = `untouched-${testInfo.project.name}`
  const html = `<p style="padding-left: 40px">Old style ${marker}</p>`
  await seedNote(html)
  const before = await stored(marker)
  await signIn(page)
  await page.getByText(`Old style ${marker}`).first().click()
  await expect(page.locator('.note-editor .ProseMirror')).toContainText(marker)
  await page.getByText('Notes on the Analytical Engine').first().click()
  await page.waitForTimeout(1500)

  const after = await stored(marker)
  expect(after.version).toBe(before.version)
  expect(after.note).toBe(html)
})

test('a new standalone note opens ready to type, and is kept', async ({ page }, testInfo) => {
  const marker = `standalone-${testInfo.project.name}`
  await signIn(page)

  await page.getByRole('button', { name: 'New Note' }).click()
  await page.getByRole('menuitem', { name: 'New Standalone Note' }).click()
  await expect(page.locator('.note-editor .ProseMirror')).toBeFocused()
  await page.keyboard.type(`Fresh ${marker}`)
  await expect(page.locator('.note-pane__state')).toHaveText('Saved.')

  const note = await stored(marker)
  expect(note.note).toBe(`<div data-schema-version="9"><p>Fresh ${marker}</p>\n</div>`)
  expect(note.parentItem).toBeUndefined()
  await expect(page.locator('.detail__title')).toHaveText(`Fresh ${marker}`)
})

test('a note added to an item goes under it', async ({ page }, testInfo) => {
  const marker = `child-${testInfo.project.name}`
  await signIn(page)
  await page.getByText('Letter to Charles Babbage').first().click()

  await page.getByRole('button', { name: 'Add Note' }).click()
  await expect(page.locator('.note-editor .ProseMirror')).toBeFocused()
  await page.keyboard.type(`Child ${marker}`)
  await expect(page.locator('.note-pane__state')).toHaveText('Saved.')

  const { baseURL } = state()
  const found = await fetch(`${baseURL}/users/1/items?q=${encodeURIComponent('Letter to Charles Babbage')}`, {
    headers: headers(),
  })
  const [letter] = (await found.json()) as [{ key: string }]
  expect((await stored(marker)).parentItem).toBe(letter.key)
})

test('a note changed elsewhere reaches the open editor while nothing is unsaved', async ({ page }, testInfo) => {
  const marker = `pushed-${testInfo.project.name}`
  await seedNote(`<p>Before ${marker}</p>`)
  await signIn(page)
  await page.getByText(`Before ${marker}`).first().click()
  await expect(page.locator('.note-editor .ProseMirror')).toContainText(`Before ${marker}`)

  const { baseURL } = state()
  const note = await stored(marker)
  const written = await fetch(`${baseURL}/users/1/items/${note.key}`, {
    method: 'PATCH',
    headers: { ...headers(), 'If-Unmodified-Since-Version': String(note.version) },
    body: JSON.stringify({ note: `<p>After ${marker}</p>` }),
  })
  expect(written.status).toBe(204)

  await expect(page.locator('.note-editor .ProseMirror')).toContainText(`After ${marker}`)
})

test('the note editor has no serious accessibility problems', async ({ page }) => {
  await signIn(page)
  await page.getByText('Notes on the Analytical Engine').first().click()
  await page.getByText('The engine weaves algebraic patterns.').first().click()
  await expect(page.locator('.note-editor .ProseMirror')).toBeVisible()
  expect(await accessibilityProblems(page)).toEqual([])

  await page.getByRole('button', { name: 'Format Text' }).click()
  expect(await accessibilityProblems(page)).toEqual([])
})
