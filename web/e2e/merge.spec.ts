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

async function seedPair(label: string, identifier?: string) {
  const { baseURL, key } = state()
  const headers = { 'Zotero-API-Key': key, 'Content-Type': 'application/json' }
  const isbns = ['9780262510875', '9780131103627', '9780201633610', '9780321125217']
  const index = (label.startsWith('Stale') ? 2 : 0) + (label.endsWith('phone') ? 1 : 0)
  const isbn = identifier ?? isbns[index]!
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
  const row = page.locator('.duplicate-group__row').filter({ hasText: `${label} chosen` })
  if (info.project.name === 'phone') await row.tap()
  else await row.click()
  const pane = page.locator('.merge-pane')
  await expect(pane.locator('select[name="merge-master"]')).toHaveValue(pair.master.key)
  await pane.locator('select[name="merge-title"]').selectOption('1')
  await pane.locator('[data-merge-review]').click()
  await expect(pane.locator('[data-merge-confirm]')).toBeFocused()
  await pane.locator('[data-merge-cancel]').click()
  await expect(pane.locator('[data-merge-review]')).toBeFocused()
  await expect(pane.locator('select[name="merge-title"]')).toHaveValue('1')
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
  const row = page.locator('.duplicate-group__row').filter({ hasText: `${label} chosen` })
  if (info.project.name === 'phone') await row.tap()
  else await row.click()
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
  await pane.locator('select[name="merge-title"]').selectOption('1')
  await pane.locator('[data-merge-review]').click()
  await pane.locator('[data-merge-confirm]').click()
  await expect(page.getByText('Items merged.', { exact: true })).toBeVisible()
})


test('duplicate groups can be tapped, inspected and refined without modifier keys', async ({ page }, info) => {
  const phone = info.project.name === 'phone'
  const first = `Grouped first ${info.project.name}`
  const second = `Grouped second ${info.project.name}`
  await seedPair(first, phone ? '9780132350884' : '9780596007126')
  const pair = await seedPair(second, phone ? '9780201616224' : '9781491957660')
  await signIn(page)
  await page.locator('.library__scope').filter({ hasText: 'Duplicate Items' }).click()
  const tap = async (title: string) => {
    const row = page.locator('.duplicate-group__row').filter({ hasText: title })
    if (phone) await row.tap()
    else await row.click()
  }
  await tap(`${first} chosen`)
  await expect(page.locator('.merge-pane')).toBeInViewport()
  const firstGroup = page.locator('.duplicate-group').filter({ hasText: `${first} original` })
  const secondGroup = page.locator('.duplicate-group').filter({ hasText: `${second} original` })
  await expect(firstGroup.locator('[aria-pressed="true"]')).toHaveCount(2)
  await tap(`${second} chosen`)
  await expect(firstGroup.locator('[aria-pressed="true"]')).toHaveCount(0)
  await expect(secondGroup.locator('[aria-pressed="true"]')).toHaveCount(2)
  const pane = page.locator('.merge-pane')
  await pane.getByRole('button', { name: 'Edit', exact: true }).click()
  await pane.locator(`[data-merge-inspect="${pair.other.key}"]`).click()
  await expect(page.locator('.detail__title')).toHaveText(`${second} chosen`)
  await page.getByRole('button', { name: 'Back', exact: true }).click()
  await expect(pane).toBeVisible()
  await page.getByRole('button', { name: 'Search this library', exact: true }).click()
  const search = page.getByRole('searchbox', { name: 'Search this library' })
  await search.fill(`${second} chosen`)
  await expect(page.locator('.duplicate-group')).toHaveCount(1)
  await pane.getByRole('button', { name: 'Export…', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Export…', exact: true })
  await dialog.getByLabel('Format:').selectOption('ris')
  for (const scope of ['selection', 'view']) {
    await dialog.locator(`input[value="${scope}"]`).check()
    const href = (await dialog.getByRole('link', { name: 'Export', exact: true }).getAttribute('href'))!
    const text = await page.evaluate(async (url) => (await fetch(url)).text(), href)
    expect(text.match(/TY  - /g)).toHaveLength(2)
    expect(text).toContain(`${second} original`)
    expect(text).toContain(`${second} chosen`)
  }
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await search.fill('')
  await expect(firstGroup).toHaveCount(1)
  await pane.getByRole('button', { name: 'Select', exact: true }).click()
  const included = pane.getByRole('checkbox', { name: `Select “${second} chosen”`, exact: true })
  await included.uncheck()
  await expect(secondGroup.locator('[aria-pressed="true"]')).toHaveCount(1)
  await expect(pane.locator('[data-merge-review]')).toBeDisabled()
  await included.check()
  await expect(secondGroup.locator('[aria-pressed="true"]')).toHaveCount(2)
  await pane.locator('select[name="merge-master"]').selectOption(pair.other.key)
  await expect(secondGroup.locator('[data-row]').first()).toHaveAttribute('data-row', pair.other.key)
  if (phone) {
    for (const control of [pane.getByRole('button', { name: 'Edit', exact: true }), pane.locator('select[name="merge-master"]')]) {
      expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(await accessibilityProblems(page)).toEqual([])
  await page.screenshot({ path: `/tmp/altero-duplicate-groups-${info.project.name}.png`, fullPage: true })
})
