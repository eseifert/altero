import { expect, signIn, test } from './state'

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

test('the app shell opens offline, and nothing of a library is kept', async ({ page, context }) => {
  await signIn(page)
  await page.evaluate(() => navigator.serviceWorker.ready)
  // Controlled from the next load on: the first was fetched before the worker.
  await page.reload()
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true)
  await page.getByText('Notes on the Analytical Engine').first().click()

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
  await context.setOffline(false)
})
