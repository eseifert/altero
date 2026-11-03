import { createHash } from 'node:crypto'
import { once } from 'node:events'
import { createServer } from 'node:http'

import type { Page } from '@playwright/test'

import { accessibilityProblems, expect, state, test } from './state'

/** Two deployment stamps of the built app over real HTTP, with real workers.
 * Only the page/worker build ids change; assets and API responses come from the
 * actual server. Each test gets its own origin, without mutating shared files. */
async function deployment() {
  const { baseURL } = state()
  const html = await (await fetch(`${baseURL}/app/`)).text()
  const script = await (await fetch(`${baseURL}/app/sw.js`)).text()
  const build = /name="altero-build" content="([a-f0-9]{16})"/.exec(html)?.[1]
  expect(build).toBeDefined()
  expect(script).toContain(build!)
  const next = createHash('sha256').update(`${build}:next`).digest('hex').slice(0, 16)
  let current = build!
  const server = createServer(async (request, response) => {
    try {
      const upstream = await fetch(`${baseURL}${request.url}`, {
        headers: request.headers.cookie ? { cookie: request.headers.cookie } : {},
        redirect: 'manual',
      })
      const headers = Object.fromEntries(upstream.headers)
      for (const name of ['content-length', 'content-encoding', 'transfer-encoding', 'etag', 'last-modified']) delete headers[name]
      let body: string | Uint8Array = new Uint8Array(await upstream.arrayBuffer())
      if (request.url === '/app/sw.js') body = script.replaceAll(build!, current)
      else if (headers['content-type']?.startsWith('text/html')) body = html.replaceAll(build!, current)
      response.writeHead(upstream.status, headers)
      response.end(body)
    } catch {
      response.writeHead(502)
      response.end('The test backend did not answer')
    }
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('No deployment port')
  return {
    url: `http://127.0.0.1:${address.port}/app/sign-in`, build, next,
    upgrade: () => { current = next },
    close: async () => {
      server.closeAllConnections()
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
    },
  }
}

async function controlledBuild(page: Page) {
  return page.evaluate(async () => {
    const worker = navigator.serviceWorker.controller
    if (!worker) return null
    return new Promise<string | null>((resolve) => {
      const channel = new MessageChannel()
      const timeout = setTimeout(() => resolve(null), 3000)
      channel.port1.onmessage = ({ data }) => {
        clearTimeout(timeout)
        channel.port1.close()
        resolve(data.build)
      }
      worker.postMessage({ type: 'build' }, [channel.port2])
    })
  })
}

async function observeOffers(page: Page) {
  await page.addInitScript(() => {
    const seen = new WeakSet<Element>()
    ;(window as unknown as { updateOffers: number }).updateOffers = 0
    new MutationObserver(() => {
      for (const toast of document.querySelectorAll('.toast')) {
        if (toast.textContent?.includes('A new version of altero is ready.') && !seen.has(toast)) {
          seen.add(toast)
          ;(window as unknown as { updateOffers: number }).updateOffers++
        }
      }
    }).observe(document, { subtree: true, childList: true })
  })
}

const offers = (page: Page) => page.evaluate(() => (window as unknown as { updateOffers: number }).updateOffers)

test('an open page polls for an upgrade once; a fresh tab activates it quietly and the old tab can reload', async ({ page, context }) => {
  const deployed = await deployment()
  try {
    await observeOffers(page)
    await page.clock.install()
    await page.goto(deployed.url)
    await expect.poll(() => controlledBuild(page)).toBe(deployed.build)
    expect(await offers(page)).toBe(0)
    deployed.upgrade()
    await page.clock.fastForward(5 * 60 * 1000)
    const toast = page.locator('.toast').filter({ hasText: 'A new version of altero is ready.' })
    await expect(toast).toHaveCount(1)
    await toast.getByRole('button', { name: 'Reload', exact: true }).focus()
    await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready
      await registration.update()
      await registration.update()
    })
    expect(await offers(page)).toBe(1)

    const fresh = await context.newPage()
    await observeOffers(fresh)
    await fresh.goto(deployed.url)
    await expect.poll(() => controlledBuild(fresh)).toBe(deployed.next)
    expect(await offers(fresh)).toBe(0)
    await expect(fresh.locator('.toast')).toHaveCount(0)
    await expect.poll(() => controlledBuild(page)).toBe(deployed.next)
    expect(await offers(page)).toBe(1)
    expect(await accessibilityProblems(fresh)).toEqual([])
    await fresh.close()

    await Promise.all([
      page.waitForEvent('load'), toast.getByRole('button', { name: 'Reload', exact: true }).click(),
    ])
    await expect(page.locator('meta[name="altero-build"]')).toHaveAttribute('content', deployed.next)
    await expect.poll(() => controlledBuild(page)).toBe(deployed.next)
    expect(await offers(page)).toBe(0)
  } finally {
    await deployed.close()
  }
})

test('manually reloading after deployment loads the current interface without an update prompt', async ({ page }) => {
  const deployed = await deployment()
  try {
    await observeOffers(page)
    await page.goto(deployed.url)
    await expect.poll(() => controlledBuild(page)).toBe(deployed.build)
    deployed.upgrade()
    await page.reload()
    await expect(page.locator('meta[name="altero-build"]')).toHaveAttribute('content', deployed.next)
    await expect.poll(() => controlledBuild(page)).toBe(deployed.next)
    await expect(page.locator('.toast')).toHaveCount(0)
    expect(await offers(page)).toBe(0)
    expect(await accessibilityProblems(page)).toEqual([])
  } finally {
    await deployed.close()
  }
})
