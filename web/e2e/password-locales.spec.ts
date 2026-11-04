import { accessibilityProblems, expect, PASSWORD, signIn, state, test } from './state'

for (const [tag, labels] of Object.entries({
  es: {
    own: 'Su contraseña', replacement: 'Nueva contraseña para esta cuenta',
    set: 'Establecer contraseña', send: 'Enviar un enlace de contraseña', new: 'Nueva contraseña',
    adminNotice: 'Contraseña establecida. Se cerró la sesión en los demás navegadores de esta cuenta.',
    resetNotice: 'Contraseña establecida. Se cerró la sesión en todos los demás navegadores.',
  },
  'pt-PT': {
    own: 'A sua palavra-passe', replacement: 'Nova palavra-passe para esta conta',
    set: 'Definir palavra-passe', send: 'Enviar uma ligação de palavra-passe', new: 'Nova palavra-passe',
    adminNotice: 'Palavra-passe definida. A sessão foi terminada nos outros navegadores desta conta.',
    resetNotice: 'Palavra-passe definida. A sessão foi terminada em todos os outros navegadores.',
  },
})) {
  test.describe(`password session notices in ${tag}`, () => {
    test.use({ locale: tag })

    test('describes session revocation while the other browser stays open', async ({ page, browser }, info) => {
      test.setTimeout(60_000)
      await signIn(page)
      const csrf = (await page.context().cookies()).find(cookie => cookie.name === 'altero_csrf')!.value
      const username = `sessions${tag}${info.project.name}`.replace(/[^a-z]/gi, '').toLowerCase()
      const made = await page.request.post('/web/admin/users', {
        headers: { 'X-CSRF-Token': decodeURIComponent(csrf) },
        data: { username, displayName: 'Session wording check', password: PASSWORD, currentPassword: PASSWORD },
      })
      expect(made.status()).toBe(201)
      const other = await browser.newContext({ baseURL: state().baseURL, locale: tag })
      const otherPage = await other.newPage()
      const login = async (password: string) => {
        await otherPage.goto('/app/sign-in')
        await otherPage.locator('input[autocomplete=username]').fill(username)
        await otherPage.locator('input[autocomplete=current-password]').fill(password)
        await otherPage.locator('button[type=submit]').click()
        await otherPage.waitForURL(/\/app\/library/)
        expect((await otherPage.request.get('/web/account')).status()).toBe(200)
      }
      try {
        await login(PASSWORD)
        await page.goto('/app/admin/accounts')
        await page.locator('.accounts__row').filter({ hasText: username }).click()
        const detail = page.locator('.accounts__detail')
        await detail.getByLabel(labels.own, { exact: true }).fill(PASSWORD)
        const replacement = 'Replacement password for session checks'
        await detail.getByLabel(labels.replacement, { exact: true }).fill(replacement)
        await detail.getByRole('button', { name: labels.set, exact: true }).click()
        await expect(page.locator('.section-panel__notice')).toHaveText(labels.adminNotice)
        expect((await otherPage.request.get('/web/account')).status()).toBe(401)
        expect(otherPage.isClosed()).toBe(false)
        await page.screenshot({ path: info.outputPath(`${tag}-admin-password.png`), fullPage: true })
        expect(await accessibilityProblems(page)).toEqual([])

        await login(replacement)
        await detail.getByRole('button', { name: labels.send, exact: true }).click()
        const link = page.locator('.accounts__link')
        await expect(link).toBeVisible()
        const url = (await link.textContent())!.trim()
        expect(new URL(url).origin).toBe(state().baseURL)
        await page.goto(url)
        const finalPassword = 'Final password for session checks'
        await page.getByLabel(labels.new, { exact: true }).fill(finalPassword)
        await page.getByRole('button', { name: labels.set, exact: true }).click()
        await expect(page.locator('.auth-form__lead')).toHaveText(labels.resetNotice)
        expect((await otherPage.request.get('/web/account')).status()).toBe(401)
        expect(otherPage.isClosed()).toBe(false)
        expect((await page.request.get('/web/account')).status()).toBe(200)
        await page.screenshot({ path: info.outputPath(`${tag}-reset-password.png`), fullPage: true })
        expect(await accessibilityProblems(page)).toEqual([])
        await login(finalPassword)
      } finally {
        await other.close()
      }
    })
  })
}
