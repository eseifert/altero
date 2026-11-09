import { accessibilityProblems, expect, signIn, state, test } from './state'

test('cancelling group deletion preserves items and confirming removes the library', async ({ page, request }, info) => {
  const name = `Group deletion ${info.project.name}`
  const headers = { 'Zotero-API-Key': state().key }
  const created = await request.post('/groups', { headers, data: { name } })
  expect(created.ok()).toBe(true)
  const group = await created.json()
  await signIn(page)
  const libraries = await (await page.request.get('/web/libraries')).json()
  const library = libraries.find((entry: { type: string; ownerId: number }) => entry.type === 'group' && entry.ownerId === group.id)
  const csrf = (await page.context().cookies()).find(cookie => cookie.name === 'altero_csrf')!.value
  const made = await page.request.post(`/web/libraries/${library.id}/items`, {
    headers: { 'X-CSRF-Token': decodeURIComponent(csrf) }, data: { itemType: 'book' },
  })
  expect(made.status()).toBe(201)
  const { key } = await made.json()
  const item = async () => (await (await page.request.get(`/web/libraries/${library.id}/items/${key}`)).json())
  const original = await item()
  await page.goto('/app/groups')
  await page.locator('.groups__list button').filter({ hasText: name }).click()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  const confirmation = page.locator('[role=alert]')
  await expect(confirmation).toContainText(name)
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(await item()).toEqual(original)
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.screenshot({ path: info.outputPath('delete-group.png'), fullPage: true })
  expect(await accessibilityProblems(page)).toEqual([])
  await confirmation.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.locator('.groups__notice')).toBeVisible()
  expect((await request.get(`/groups/${group.id}`, { headers })).status()).toBe(404)
  expect((await page.request.get(`/web/libraries/${library.id}/items`)).status()).toBe(404)
})
