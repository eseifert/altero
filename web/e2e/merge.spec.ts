import { expect, signIn, state, test } from './state'

test('a browser merge request keeps the chosen title and survives a reload', async ({ page }, info) => {
  const title = `Merged by ${info.project.name}`
  const seeded = await fetch(`${state().baseURL}/users/1/items`, {
    method: 'POST',
    headers: { 'Zotero-API-Key': state().key, 'Content-Type': 'application/json' },
    body: JSON.stringify([
      { itemType: 'book', title: `Master for ${info.project.name}` },
      { itemType: 'book', title: `Duplicate for ${info.project.name}` },
    ]),
  })
  expect(seeded.status).toBe(200)
  const made = (await seeded.json()).successful as Record<string, { key: string }>
  const master = made['0']!.key
  const other = made['1']!.key
  await signIn(page)
  // P4.2 supplies the endpoint; the merge pane is P4.3. Fetch from the actual
  // browser so its session cookie and CSRF cookie are the credentials used.
  const answer = await page.evaluate(async ({ master, other, title }) => {
    const libraries = await (await fetch('/web/libraries')).json()
    const library = libraries.find((row: { type: string }) => row.type === 'user')
    const csrf = decodeURIComponent(
      document.cookie.split('; ').find((cookie) => cookie.startsWith('altero_csrf='))!.split('=')[1]!,
    )
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
      'If-Unmodified-Since-Version': String(library.version),
    }
    const body = JSON.stringify({ master, others: [other], fields: { title } })
    const path = `/web/libraries/${library.id}/items/merge`
    const response = await fetch(path, { method: 'POST', headers, body })
    const payload = await response.json()
    const retry = await fetch(path, { method: 'POST', headers, body })
    return { status: response.status, payload, retry: retry.status }
  }, { master, other, title })
  expect(answer.status).toBe(200)
  expect(answer.payload.items[0]).toMatchObject({ key: master, data: { title } })
  expect(answer.payload.items.find((item: { key: string }) => item.key === other).data.deleted).toBe(1)
  expect(answer.retry).toBe(412)
  await page.reload()
  await page.getByText(title, { exact: true }).first().click()
  await expect(page.locator('.detail__title')).toHaveText(title)
})
