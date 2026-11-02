import type { Page } from '@playwright/test'

import { accessibilityProblems, expect, signIn, state, test } from './state'

async function api(path: string, body?: unknown) {
  const { baseURL, key } = state()
  const response = await fetch(`${baseURL}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Zotero-API-Key': key, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  expect(response.ok).toBeTruthy()
  return response.json()
}

async function seed(page: Page, suffix: string) {
  const title = `Copy undo ${suffix}`
  const name = `Copy destination ${suffix}`
  const created = await api('/groups', { name })
  const group = { id: created.id, name }
  const made = await api('/users/1/items', [{ itemType: 'book', title }])
  expect(made.failed).toEqual({})
  const original = made.successful['0'].key as string
  await api('/users/1/items', [{ itemType: 'note', parentItem: original, note: '<p>Keep this note</p>' }])
  await signIn(page)
  const libraries = await (await page.request.get('/web/libraries')).json()
  const target = libraries.find((entry: { type: string; ownerId: number }) =>
    entry.type === 'group' && entry.ownerId === group.id)
  const source = libraries.find((entry: { type: string }) => entry.type === 'user')
  return { title, group, original, target, source }
}

async function copy(page: Page, title: string, target: number) {
  await page.locator('.library__row').filter({ hasText: title }).click()
  await page.locator('.detail').getByRole('button', { name: 'Move or copy…', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox').selectOption(`library:${target}`)
  const written = page.waitForResponse((response) =>
    response.url().endsWith('/items/copy') && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  const response = await written
  expect(response.status()).toBe(201)
  return response.json()
}

async function destinationItem(page: Page, library: number, key: string) {
  const response = await page.request.get(`/web/libraries/${library}/items/${key}`)
  expect(response.ok()).toBe(true)
  return response.json()
}

test('undo after navigation trashes only the copy and leaves its note and bytes recoverable', async ({ page }, info) => {
  const { title, original, source, target, group } = await seed(page, info.project.name)
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === 'altero_csrf')!.value
  const bytes = Buffer.from('Shared original and copied attachment bytes')
  const uploaded = await page.request.post(
    `/web/libraries/${source.id}/attachments?filename=keep.txt&parentItem=${original}`, {
      headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'text/plain' }, data: bytes,
    },
  )
  expect(uploaded.status()).toBe(201)
  const originalFile = (await uploaded.json()).key
  const answer = await copy(page, title, target.id)
  const copied = answer.items[0].key
  const toast = page.locator('.toast').filter({ hasText: 'Copied' })
  await expect(toast.getByRole('button', { name: 'Undo', exact: true })).toBeVisible()
  await page.locator('.library__library').filter({ hasText: group.name }).click()
  await expect(page.locator('.library__row').filter({ hasText: title })).toBeVisible()
  await toast.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(page.locator('.toasts')).toContainText('Change undone.')
  await expect(page.locator('.library__row').filter({ hasText: title })).toHaveCount(0)
  expect((await api(`/users/1/items/${original}`)).data.deleted).toBeUndefined()
  expect((await destinationItem(page, target.id, copied)).data.deleted).toBe(1)
  expect(await accessibilityProblems(page)).toEqual([])

  await page.getByRole('button', { name: 'Trash', exact: true }).click()
  await page.locator('.library__row').filter({ hasText: title }).click()
  await page.locator('.detail').getByRole('button', { name: 'Restore to Library', exact: true }).click()
  await expect(page.locator('.toasts')).toContainText('Items restored.')
  await page.reload()
  await page.locator('.library__library').filter({ hasText: group.name }).click()
  await page.locator('.library__row').filter({ hasText: title }).click()
  await expect(page.locator('.detail__child').filter({ hasText: 'Keep this note' })).toBeVisible()
  const children = (await (await page.request.get(`/web/libraries/${target.id}/items/${copied}/children`)).json()).items
  const attachment = children.find((item: { data: { itemType: string } }) => item.data.itemType === 'attachment')
  for (const [library, key] of [[source.id, originalFile], [target.id, attachment.key]]) {
    const downloaded = await page.request.get(`/web/libraries/${library}/items/${key}/file`)
    expect(downloaded.ok()).toBe(true)
    expect(await downloaded.body()).toEqual(bytes)
  }
})

test('a write to the destination invalidates a copy undo without trashing the copy', async ({ page }, info) => {
  const { title, original, target } = await seed(page, `stale ${info.project.name}`)
  const answer = await copy(page, title, target.id)
  const toast = page.locator('.toast').filter({ hasText: 'Copied' })
  await expect(toast.getByRole('button', { name: 'Undo', exact: true })).toBeVisible()
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === 'altero_csrf')!.value
  const changed = await page.request.post(`/web/libraries/${target.id}/collections`, {
    headers: { 'X-CSRF-Token': csrf }, data: { name: 'A later destination write' },
  })
  expect(changed.status()).toBe(201)
  await toast.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(page.locator('.toasts')).toContainText('Undo is no longer available because the library changed.')
  expect((await destinationItem(page, target.id, answer.items[0].key)).data.deleted).toBeUndefined()
  expect((await api(`/users/1/items/${original}`)).data.deleted).toBeUndefined()
})
