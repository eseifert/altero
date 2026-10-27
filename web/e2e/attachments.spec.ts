import { createHash } from 'node:crypto'

import type { Page } from '@playwright/test'

import { accessibilityProblems, expect, signIn, state, test } from './state'

/* Both projects run against the one seeded library, so every item made here
   says which project made it. */

const headers = () => ({ 'Zotero-API-Key': state().key, 'Content-Type': 'application/json' })

interface Stored {
  key: string
  data: Record<string, string | undefined>
}

async function seedBook(title: string): Promise<string> {
  const made = await fetch(`${state().baseURL}/users/1/items`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify([{ itemType: 'book', title }]),
  })
  return ((await made.json()) as { successful: Record<string, { key: string }> }).successful['0']!.key
}

/** The children of ``key`` as a desktop syncing would read them. */
async function childrenOf(key: string): Promise<Stored[]> {
  const found = await fetch(`${state().baseURL}/users/1/items/${key}/children`, { headers: headers() })
  return (await found.json()) as Stored[]
}

/** The bytes a desktop downloads for ``key``: the v3 redirect, then where it points. */
async function downloaded(key: string): Promise<Buffer> {
  const redirect = await fetch(`${state().baseURL}/users/1/items/${key}/file`, {
    headers: headers(),
    redirect: 'manual',
  })
  expect(redirect.status).toBe(302)
  const served = await fetch(redirect.headers.get('Location')!)
  return Buffer.from(await served.arrayBuffer())
}

const md5 = (bytes: Buffer) => createHash('md5').update(bytes).digest('hex')

/**
 * Open the item pane's *Add Attachment* menu.
 *
 * The button is at the foot of a pane that scrolls, and the menu closes when
 * the page scrolls under it -- which the scroll that brings the button into
 * view can do a moment after the click. So the button is scrolled to first and
 * the menu asked for again until it stays.
 */
async function attachMenu(page: Page): Promise<void> {
  const button = page.locator('.detail').getByRole('button', { name: 'Add Attachment' })
  await button.scrollIntoViewIfNeeded()
  await expect(async () => {
    if ((await button.getAttribute('aria-expanded')) !== 'true') await button.click()
    await expect(page.getByRole('menu', { name: 'Add Attachment' })).toBeVisible({ timeout: 500 })
  }).toPass()
}

async function openBook(page: Page, title: string): Promise<void> {
  await signIn(page)
  await page.getByText(title).first().click()
  await expect(page.locator('.detail__title')).toHaveText(title)
}

test('a file attached in the browser is the file a desktop downloads', async ({ page }, testInfo) => {
  const title = `Attached by ${testInfo.project.name}`
  const book = await seedBook(title)
  const bytes = Buffer.from(`%PDF-1.7\n${title}\n`)
  await openBook(page, title)

  await attachMenu(page)
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('menuitem', { name: 'Attach File…' }).click()
  await (await chooser).setFiles({ name: 'paper.pdf', mimeType: 'application/pdf', buffer: bytes })

  // The desktop's title for a first PDF, and the pane lists it.
  await expect(page.locator('.detail__children').getByText('PDF', { exact: true })).toBeVisible()
  const [attachment] = await childrenOf(book)
  expect(attachment!.data).toMatchObject({
    itemType: 'attachment',
    linkMode: 'imported_file',
    title: 'PDF',
    filename: 'paper.pdf',
    contentType: 'application/pdf',
    md5: md5(bytes),
  })
  expect(await downloaded(attachment!.key)).toEqual(bytes)
  expect(await accessibilityProblems(page)).toEqual([])
})

test('a file dropped from the computer onto an item goes under it', async ({ page }, testInfo) => {
  const title = `Dropped on by ${testInfo.project.name}`
  const book = await seedBook(title)
  await openBook(page, title)

  await page.locator('.detail').evaluate((pane) => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['dropped bytes'], 'notes.txt', { type: 'text/plain' }))
    for (const type of ['dragenter', 'dragover', 'drop']) {
      pane.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: transfer }))
    }
  })

  await expect(page.locator('.detail__children').getByText('notes')).toBeVisible()
  const [attachment] = await childrenOf(book)
  expect(attachment!.data).toMatchObject({ filename: 'notes.txt', title: 'notes' })
  expect((await downloaded(attachment!.key)).toString()).toBe('dropped bytes')
})

test('a file is replaced, and a web link attached', async ({ page }, testInfo) => {
  const title = `Replaced by ${testInfo.project.name}`
  const book = await seedBook(title)
  await openBook(page, title)

  await attachMenu(page)
  let chooser = page.waitForEvent('filechooser')
  await page.getByRole('menuitem', { name: 'Attach File…' }).click()
  await (await chooser).setFiles({ name: 'draft.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF draft') })
  await page.locator('.detail__children').getByText('PDF', { exact: true }).click()

  chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: 'Replace File…' }).click()
  await (await chooser).setFiles({ name: 'final.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF final') })
  await expect.poll(async () => (await childrenOf(book))[0]?.data.filename).toBe('final.pdf')
  const [replaced] = await childrenOf(book)
  expect(replaced!.data.title).toBe('PDF')
  expect((await downloaded(replaced!.key)).toString()).toBe('%PDF final')

  await page.getByText(title).first().click()
  await attachMenu(page)
  await page.getByRole('menuitem', { name: 'Attach Web Link…' }).click()
  await page.getByRole('textbox', { name: 'Link', exact: true }).fill('example.org/paper')
  await page.getByRole('button', { name: 'Attach', exact: true }).click()

  await expect(page.locator('.detail__title')).toHaveText('paper')
  const link = (await childrenOf(book)).find((child) => child.data.linkMode === 'linked_url')
  expect(link!.data).toMatchObject({ url: 'http://example.org/paper', title: 'paper' })
})
