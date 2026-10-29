import { accessibilityProblems, expect, signIn, state, test } from './state'

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
  // Exercise the endpoint directly as well as through the pane below. The
  // actual browser supplies both the session and CSRF cookies.
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

async function seedPair(label: string) {
  const { baseURL, key } = state()
  const headers = { 'Zotero-API-Key': key, 'Content-Type': 'application/json' }
  const isbns = ['9780262510875', '9780131103627', '9780201633610', '9780321125217']
  const index = (label.startsWith('Stale') ? 2 : 0) + (label.endsWith('phone') ? 1 : 0)
  const isbn = isbns[index]!
  const response = await fetch(`${baseURL}/users/1/items`, {
    method: 'POST', headers,
    body: JSON.stringify([
      { itemType: 'book', title: `${label} original`, ISBN: isbn, dateAdded: '2020-01-01T00:00:00Z' },
      { itemType: 'book', title: `${label} chosen`, ISBN: isbn, dateAdded: '2025-01-01T00:00:00Z' },
    ]),
  })
  expect(response.status).toBe(200)
  const made = (await response.json()).successful as Record<string, { key: string; version: number }>
  return { master: made['0']!, other: made['1']!, headers, baseURL }
}

test('the duplicates pane confirms field choices and refreshes the list', async ({ page }, info) => {
  const label = `Merge pane ${info.project.name}`
  const pair = await seedPair(label)
  await signIn(page)
  await page.locator('.library__scope').filter({ hasText: 'Duplicate Items' }).click()
  await page.getByRole('button', { name: 'Select', exact: true }).click()
  await page.getByRole('checkbox', { name: `Select “${label} original”`, exact: true }).check()
  await page.getByRole('checkbox', { name: `Select “${label} chosen”`, exact: true }).check()
  const pane = page.locator('.merge-pane')
  await expect(pane.locator('input[name="merge-master"]:checked')).toHaveValue(pair.master.key)
  await pane.locator('input[name="merge-title"][value="1"]').check()
  await pane.locator('[data-merge-review]').click()
  await expect(pane.locator('[data-merge-confirm]')).toBeFocused()
  await pane.locator('[data-merge-cancel]').click()
  await expect(pane.locator('[data-merge-review]')).toBeFocused()
  await expect(pane.locator('input[name="merge-title"]:checked')).toHaveValue('1')
  await pane.locator('[data-merge-review]').click()
  expect(await accessibilityProblems(page)).toEqual([])
  await page.screenshot({ path: `/tmp/altero-p43-${info.project.name}.png`, fullPage: true })
  const request = page.waitForRequest((request) => request.method() === 'POST' && request.url().includes('/items/merge'))
  await pane.locator('[data-merge-confirm]').click()
  expect((await request).postDataJSON()).toMatchObject({
    master: pair.master.key, others: [pair.other.key], fields: { title: `${label} chosen` },
  })
  await expect(page.getByText('Items merged.', { exact: true })).toBeVisible()
  await expect(pane).toHaveCount(0)
  // The selected pair is gone from duplicates. Check persistent state through
  // the desktop API too, independently of the browser's refreshed list.
  const response = await fetch(`${pair.baseURL}/users/1/items/${pair.other.key}`, { headers: pair.headers })
  expect((await response.json()).data.deleted).toBe(1)
  await page.reload()
  await page.getByText(`${label} chosen`, { exact: true }).first().click()
  await expect(page.locator('.detail__title')).toHaveText(`${label} chosen`)
})

test('a stale merge requires reloading and reviewing the selected items', async ({ page }, info) => {
  const label = `Stale merge ${info.project.name}`
  const pair = await seedPair(label)
  await signIn(page)
  await page.locator('.library__scope').filter({ hasText: 'Duplicate Items' }).click()
  await page.getByRole('button', { name: 'Select', exact: true }).click()
  await page.getByRole('checkbox', { name: `Select “${label} original”`, exact: true }).check()
  await page.getByRole('checkbox', { name: `Select “${label} chosen”`, exact: true }).check()
  const pane = page.locator('.merge-pane')
  await expect(pane.locator('[data-merge-review]')).toBeVisible()
  const changed = await fetch(`${pair.baseURL}/users/1/items/${pair.other.key}`, {
    method: 'PATCH', headers: { ...pair.headers, 'If-Unmodified-Since-Version': String(pair.other.version) },
    body: JSON.stringify({ title: `${label} updated elsewhere` }),
  })
  expect(changed.status).toBe(204)
  await pane.locator('[data-merge-review]').click()
  const rejected = page.waitForResponse((response) => response.url().includes('/items/merge'))
  await pane.locator('[data-merge-confirm]').click()
  expect((await rejected).status()).toBe(412)
  await expect(pane.getByRole('alert')).toContainText('Changed elsewhere while you were editing.')
  await expect(pane.locator('[data-merge-review]')).toHaveCount(0)
  await pane.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(pane).toContainText(`${label} updated elsewhere`)
  await pane.locator('input[name="merge-title"][value="1"]').check()
  await pane.locator('[data-merge-review]').click()
  await pane.locator('[data-merge-confirm]').click()
  await expect(page.getByText('Items merged.', { exact: true })).toBeVisible()
})
