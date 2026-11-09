import { createHash, randomBytes } from 'node:crypto'

import { accessibilityProblems, expect, OAUTH_CLIENT_ID, signIn, state, test } from './state'

test.describe('consent resources', () => {
  test('confines library consent and fits long collection names on screen', async ({ page }, info) => {
    await signIn(page)
    const csrf = (await page.context().cookies()).find(cookie => cookie.name === 'altero_csrf')!.value
    const headers = { 'X-CSRF-Token': decodeURIComponent(csrf) }
    const collectionName = `Consent scope ${info.project.name}`
    const created = await page.request.post('/web/libraries/1/collections', { headers, data: { name: collectionName } })
    expect(created.status()).toBe(201)
    const collection = await created.json()
    const keyHeaders = { 'Zotero-API-Key': state().key }
    const background = await page.request.post('/users/1/collections', {
      headers: keyHeaders,
      data: Array.from({ length: 20 }, (_, index) => ({
        name: index === 0 ? `Long collection ${'W'.repeat(100)}` : `Viewport collection ${info.project.name} ${index}`,
      })),
    })
    expect(background.ok()).toBe(true)
    const added = await background.json()
    expect(added.failed).toEqual({})
    const backgroundKeys = Object.values(added.successful as Record<string, { key: string }>).map(entry => entry.key)
    const authorize = async (scope: string) => {
      const verifier = randomBytes(32).toString('base64url')
      const query = new URLSearchParams({
        client_id: OAUTH_CLIENT_ID,
        redirect_uri: `${state().baseURL}/oauth-test-callback`,
        response_type: 'code', scope,
        state: randomBytes(16).toString('base64url'),
        code_challenge: createHash('sha256').update(verifier).digest('base64url'),
        code_challenge_method: 'S256',
      })
      await page.goto(`/oauth/authorize?${query}`)
      await expect(page).toHaveURL(/\/app\/authorize\?request=/)
      await expect(page.locator('.authorize__grants')).toBeVisible()
    }
    try {
      await authorize('openid profile email')
      await expect(page.locator('.authorize__where')).toHaveCount(0)
      await page.screenshot({ path: info.outputPath('identity-consent.png'), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])

      await authorize('openid profile email library.read library.write notes.read files.read')
      await page.locator('input[name=narrowing]').last().check()
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(page.viewportSize()!.width)
      await expect(page.getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
      await page.getByRole('checkbox', { name: collectionName, exact: true }).check()
      await expect(page.getByRole('button', { name: 'Allow', exact: true })).toBeEnabled()
      await page.screenshot({ path: info.outputPath('library-consent.png'), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
      // Inspect actual pending requests; neither request is approved.
    } finally {
      expect((await page.request.delete(`/web/libraries/1/collections/${collection.key}`, { headers })).status()).toBe(204)
      const current = await page.request.get('/users/1/collections?limit=1', { headers: keyHeaders })
      expect(current.ok()).toBe(true)
      const removed = await page.request.delete(`/users/1/collections?collectionKey=${backgroundKeys.join(',')}`, {
        headers: { ...keyHeaders, 'If-Unmodified-Since-Version': current.headers()['last-modified-version']! },
      })
      expect(removed.status()).toBe(204)
    }
  })
})
