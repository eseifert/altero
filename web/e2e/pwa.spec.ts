import { expect, libraryRow, signIn, state, test } from './state'

/*
 * The installed application: what a browser asks of a page before it offers
 * to install it, and what it can open without a network.
 */

test('the manifest and its icons are there to install from', async ({ page, request }) => {
  await page.goto('/app/')
  const href = await page.locator('link[rel="manifest"]').getAttribute('href')
  expect(href).toBe('/app/manifest.webmanifest')

  const manifest = await request.get(href!)
  expect(manifest.headers()['content-type']).toContain('application/manifest+json')
  for (const icon of (await manifest.json()).icons as { src: string }[]) {
    expect((await request.get(`/app/${icon.src}`)).status()).toBe(200)
  }
})

test('the app shell opens offline, and nothing of a library is kept', async ({ page, context, request }, info) => {
  const headers = { 'Zotero-API-Key': state().key }
  const keys: string[] = []
  try {
    // Keep the original book beyond the first page, even in a focused run.
    const items = Array.from({ length: 55 }, (_, index) => ({
      itemType: 'book', title: `PWA paging ${info.project.name} ${index}`,
      dateModified: '2099-01-01T00:00:00Z',
    }))
    for (let start = 0; start < items.length; start += 50) {
      const made = await request.post('/users/1/items', { headers, data: items.slice(start, start + 50) })
      expect(made.ok()).toBe(true)
      const body = await made.json()
      expect(body.failed).toEqual({})
      keys.push(...Object.values(body.successful as Record<string, { key: string }>).map(item => item.key))
    }
    await signIn(page)
    await page.evaluate(() => navigator.serviceWorker.ready)
    // Controlled from the next load on: the first was fetched before the worker.
    await page.reload()
    await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true)
    await expect(page.locator('.library__items [data-row]')).toHaveCount(50)
    await expect(page.locator(`[data-row="${state().book}"]`)).toHaveCount(0)
    const book = await libraryRow(page, 'Notes on the Analytical Engine')
    await expect(book).toBeVisible()
    await book.click()

    const kept = await page.evaluate(async () => {
      const urls: string[] = []
      for (const name of await caches.keys()) {
        for (const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname)
      }
      return urls
    })
    expect(kept.length).toBeGreaterThan(0)
    expect(kept.every((path) => path.startsWith('/app/'))).toBe(true)

    await context.setOffline(true)
    await page.reload()
    // The shell itself, drawn by its own scripts: the header's mark.
    await expect(page.locator('.shell__bar')).toBeVisible()
  } finally {
    await context.setOffline(false)
    for (let start = 0; start < keys.length; start += 50) {
      const current = await request.get('/users/1/items?limit=1', { headers })
      expect(current.ok()).toBe(true)
      const removed = await request.delete(`/users/1/items?itemKey=${keys.slice(start, start + 50).join(',')}`, {
        headers: { ...headers, 'If-Unmodified-Since-Version': current.headers()['last-modified-version']! },
      })
      expect(removed.status()).toBe(204)
    }
  }
})
