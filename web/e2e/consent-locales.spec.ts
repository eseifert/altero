import { createHash, randomBytes } from 'node:crypto'

import { accessibilityProblems, expect, OAUTH_CLIENT_ID, signIn, state, test } from './state'

test.describe('Polish consent wording', () => {
  test.use({ locale: 'pl' })

  test('keeps informal address consistent for identity and library requests', async ({ page }, info) => {
    await signIn(page)
    await expect(page.locator('html')).toHaveAttribute('lang', 'pl')
    const csrf = (await page.context().cookies()).find(cookie => cookie.name === 'altero_csrf')!.value
    const headers = { 'X-CSRF-Token': decodeURIComponent(csrf) }
    const collectionName = `Zakres zgody ${info.project.name}`
    const created = await page.request.post('/web/libraries/1/collections', { headers, data: { name: collectionName } })
    expect(created.status()).toBe(201)
    const collection = await created.json()
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
      await expect(page.getByRole('heading', { name: 'Połącz aplikację', exact: true })).toBeVisible()
      await expect(page.locator('.authorize__lead')).toContainText('chce połączyć się z twoim kontem')
      for (const description of ['Zobaczyć twoje imię i nazwę użytkownika', 'Zobaczyć twój adres e-mail']) {
        await expect(page.locator('.authorize__grants').getByText(description, { exact: true })).toBeVisible()
      }
    }
    try {
      await authorize('openid profile email')
      await expect(page.getByText('Nie może czytać twojej biblioteki, notatek ani załączników.', { exact: true })).toBeVisible()
      await expect(page.locator('.authorize__where')).toHaveCount(0)
      await page.screenshot({ path: info.outputPath('polish-identity-consent.png'), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])

      await authorize('openid profile email library.read library.write notes.read files.read')
      for (const description of [
        'Czytać wszystko w twojej bibliotece',
        'Dodawać, zmieniać i usuwać elementy w twojej bibliotece',
        'Czytać twoje notatki',
        'Pobierać twoje załączniki',
      ]) {
        await expect(page.locator('.authorize__grants').getByText(description, { exact: true })).toBeVisible()
      }
      await page.getByRole('radio', { name: 'Tylko biblioteki i kolekcje, które wybiorę', exact: true }).check()
      await expect(page.getByText(
        'Wybranie kolekcji obejmuje też wszystko, co się w niej znajduje. Aplikacja nie będzie mogła zmieniać twoich kolekcji, zapisanych wyszukiwań, ustawień ani etykiet.',
        { exact: true },
      )).toBeVisible()
      await expect(page.getByRole('button', { name: 'Zezwól', exact: true })).toBeDisabled()
      await page.getByRole('checkbox', { name: collectionName, exact: true }).check()
      await expect(page.getByRole('button', { name: 'Zezwól', exact: true })).toBeEnabled()
      await page.screenshot({ path: info.outputPath('polish-library-consent.png'), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
      // Inspect actual pending requests; neither request is approved.
    } finally {
      expect((await page.request.delete(`/web/libraries/1/collections/${collection.key}`, { headers })).status()).toBe(204)
    }
  })
})
