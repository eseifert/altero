import type { Page } from '@playwright/test'
import type { Editor } from '@tiptap/core'

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

/** Brings up the tools: by selecting the line with a mouse, over which they
 *  float; by putting the cursor in the text on a phone, where they dock. */
async function showTools(page: Page, project: string): Promise<void> {
  const line = page.locator('.note-editor .ProseMirror p').first()
  if (project === 'desktop') await line.click({ clickCount: 3 })
  else await line.click()
}

test('the Format menu turns a line into a heading', async ({ page }, testInfo) => {
  const marker = `heading-${testInfo.project.name}`
  await seedNote(`<p>Heading ${marker}</p>`)
  await signIn(page)
  await page.getByText(`Heading ${marker}`).first().click()

  await showTools(page, testInfo.project.name)
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

test('the tools appear only when wanted, and make text bold', async ({ page }, testInfo) => {
  const marker = `bubble-${testInfo.project.name}`
  await seedNote(`<p>Bold ${marker}</p>`)
  await signIn(page)
  await page.getByText(`Bold ${marker}`).first().click()

  await expect(page.getByRole('toolbar', { name: 'Formatting' })).toBeHidden()
  // Over the selection with a mouse; on the keyboard, with the whole line
  // selected by its own handles, on a phone.
  await showTools(page, testInfo.project.name)
  if (testInfo.project.name !== 'desktop') await page.keyboard.press('ControlOrMeta+a')
  await page.getByRole('toolbar', { name: 'Formatting' }).getByRole('button', { name: 'Bold' }).click()
  await expect(page.locator('.note-pane__state')).toHaveText('Saved.')
  expect((await stored(marker)).note).toContain(`<strong>Bold ${marker}</strong>`)
})

test('"/" offers the block types and makes the one chosen', async ({ page }, testInfo) => {
  const marker = `slash-${testInfo.project.name}`
  await seedNote(`<p>Slash ${marker}</p>`)
  await signIn(page)
  await page.getByText(`Slash ${marker}`).first().click()

  const text = page.locator('.note-editor .ProseMirror')
  await text.click()
  // ProseMirror learns where a key moved the caret from `selectionchange`,
  // which the next key can overtake on a busy machine: Enter then splits the
  // line where the editor last saw the caret, at its start. Typing is read
  // from the page and needs no such wait.
  await expect(async () => {
    await page.keyboard.press('End')
    const atEnd = await text.evaluate((dom) => {
      const { $head } = (dom as HTMLElement & { editor: Editor }).editor.state.selection
      return $head.parentOffset === $head.parent.content.size
    })
    expect(atEnd).toBe(true)
  }).toPass()
  await page.keyboard.press('Enter')
  await page.keyboard.type('/num')
  await expect(page.getByRole('option')).toHaveText(['Numbered List'])
  await page.keyboard.press('Enter')
  await page.keyboard.type('first')
  await expect(page.locator('.note-pane__state')).toHaveText('Saved.')
  expect((await stored(marker)).note).toContain('<ol>\n<li>\nfirst\n</li>\n</ol>')
})

test('a note is written full screen and comes back to its pane', async ({ page }, testInfo) => {
  const marker = `full-${testInfo.project.name}`
  await seedNote(`<p>Full ${marker}</p>`)
  await signIn(page)
  await page.getByText(`Full ${marker}`).first().click()

  await page.getByRole('button', { name: 'Enter Full Screen' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.ProseMirror')).toBeFocused()
  await page.keyboard.type(' written large')
  await expect(dialog.locator('.note-pane__state')).toHaveText('Saved.')
  expect(await accessibilityProblems(page)).toEqual([])

  await page.getByRole('button', { name: 'Exit Full Screen' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('.note-pane .ProseMirror')).toContainText(`Full ${marker} written large`)
  await expect(page.getByRole('button', { name: 'Enter Full Screen' })).toBeFocused()
  expect((await stored(marker)).note).toContain(`Full ${marker} written large`)
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

test('a new standalone note opens ready to type, and is kept', async ({ page, request }, testInfo) => {
  const marker = `standalone-${testInfo.project.name}-${testInfo.repeatEachIndex}`
  // A populated sidebar puts the toolbar below the fold on a phone. Opening
  // its fixed menu must not scroll the document and dismiss the menu itself.
  const made = await request.post('/users/1/collections', {
    headers: headers(), data: Array.from({ length: 24 }, (_, index) => ({ name: `Note menu ${marker} ${index}` })),
  })
  expect(made.ok()).toBe(true)
  const created = await made.json()
  expect(created.failed).toEqual({})
  const keys = Object.values(created.successful as Record<string, { key: string }>).map(entry => entry.key)
  try {
    await signIn(page)
    await expect(page.locator('.tree__label').filter({ hasText: `Note menu ${marker}` })).toHaveCount(24)

    const button = page.getByRole('button', { name: 'New Note', exact: true })
    await button.evaluate(element => {
      element.scrollIntoView({ block: 'end' })
      // Focusing the trigger may itself scroll. Capture the page at the click,
      // before the menu opens, rather than before Playwright brings it into view.
      element.addEventListener('click', () => {
        element.setAttribute('data-opening-scroll-y', String(window.scrollY))
      }, { capture: true, once: true })
    })
    await button.click()
    await expect(page.getByRole('menu', { name: 'New Note', exact: true })).toBeVisible()
    const scroll = await button.getAttribute('data-opening-scroll-y')
    await expect.poll(() => page.evaluate(() => String(window.scrollY))).toBe(scroll)
    await page.getByRole('menuitem', { name: 'New Standalone Note' }).click()
    await expect(page.locator('.note-editor .ProseMirror')).toBeFocused()
    await page.keyboard.type(`Fresh ${marker}`)
    await expect(page.locator('.note-pane__state')).toHaveText('Saved.')

    const note = await stored(marker)
    expect(note.note).toBe(`<div data-schema-version="9"><p>Fresh ${marker}</p>\n</div>`)
    expect(note.parentItem).toBeUndefined()
    await expect(page.locator('.detail__title')).toHaveText(`Fresh ${marker}`)
  } finally {
    const version = (await request.get('/users/1/collections', { headers: headers() })).headers()['last-modified-version']!
    const removed = await request.delete(`/users/1/collections?collectionKey=${keys.join(',')}`, {
      headers: { ...headers(), 'If-Unmodified-Since-Version': version },
    })
    expect(removed.ok()).toBe(true)
  }
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

test('a note under an item goes to the trash from its pane, and back out of it', async ({ page }, testInfo) => {
  const marker = `trashed-${testInfo.project.name}`
  const { baseURL } = state()
  const found = await fetch(`${baseURL}/users/1/items?q=${encodeURIComponent('Letter to Charles Babbage')}`, {
    headers: headers(),
  })
  const [letter] = (await found.json()) as [{ key: string }]
  const made = await fetch(`${baseURL}/users/1/items`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify([{ itemType: 'note', note: `<p>Trashed ${marker}</p>`, parentItem: letter.key, tags: [], relations: {} }]),
  })
  expect(made.status).toBe(200)
  /** Whether the server holds the note in the trash; the default listing leaves trashed items out. */
  const trashed = async () => {
    const answer = await fetch(`${baseURL}/users/1/items?itemType=note&includeTrashed=1&q=${marker}`, { headers: headers() })
    const [item] = (await answer.json()) as [{ data: { deleted?: boolean } }]
    return Boolean(item.data.deleted)
  }
  await signIn(page)
  await page.getByText('Letter to Charles Babbage').first().click()
  await page.locator('.detail__child', { hasText: `Trashed ${marker}` }).click()

  await page.getByRole('button', { name: 'Move to trash' }).click()
  await expect(page.locator('.detail__title')).toHaveText('Letter to Charles Babbage')
  await expect(page.locator('.detail__child', { hasText: `Trashed ${marker}` })).toHaveCount(0)
  expect(await trashed()).toBe(true)

  await page.locator('.library__sidebar').getByText('Trash', { exact: true }).click()
  await page.getByText(`Trashed ${marker}`).first().click()
  await page.getByRole('button', { name: 'Restore to Library' }).click()
  await expect.poll(trashed).toBe(false)
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

test('the note editor has no serious accessibility problems', async ({ page }, testInfo) => {
  await signIn(page)
  await page.getByText('Notes on the Analytical Engine').first().click()
  await page.getByText('The engine weaves algebraic patterns.').first().click()
  await expect(page.locator('.note-editor .ProseMirror')).toBeVisible()
  expect(await accessibilityProblems(page)).toEqual([])

  await showTools(page, testInfo.project.name)
  expect(await accessibilityProblems(page)).toEqual([])
  await page.getByRole('button', { name: 'Format Text' }).click()
  expect(await accessibilityProblems(page)).toEqual([])
})
