import { accessibilityProblems, expect, PASSWORD, signIn, state, test } from './state'

test('password changes revoke other sessions while their browser stays open', async ({ page, browser }, info) => {
  test.setTimeout(60_000)
  await signIn(page)
  const csrf = (await page.context().cookies()).find(cookie => cookie.name === 'altero_csrf')!.value
  const username = `sessions${info.project.name}`.replace(/[^a-z]/gi, '').toLowerCase()
  const made = await page.request.post('/web/admin/users', {
    headers: { 'X-CSRF-Token': decodeURIComponent(csrf) },
    data: { username, displayName: 'Session revocation check', password: PASSWORD, currentPassword: PASSWORD },
  })
  expect(made.status()).toBe(201)
  const other = await browser.newContext({ baseURL: state().baseURL, locale: 'en-US' })
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
    await detail.getByLabel('Your password', { exact: true }).fill(PASSWORD)
    const replacement = 'Replacement password for session checks'
    await detail.getByLabel('New password for this account', { exact: true }).fill(replacement)
    await detail.getByRole('button', { name: 'Set password', exact: true }).click()
    await expect(page.locator('.section-panel__notice')).toBeVisible()
    expect((await otherPage.request.get('/web/account')).status()).toBe(401)
    expect(otherPage.isClosed()).toBe(false)
    await page.screenshot({ path: info.outputPath('admin-password.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])

    await login(replacement)
    await detail.getByRole('button', { name: 'Send a password link', exact: true }).click()
    const link = page.locator('.accounts__link')
    await expect(link).toBeVisible()
    const url = (await link.textContent())!.trim()
    expect(new URL(url).origin).toBe(state().baseURL)
    await page.goto(url)
    const finalPassword = 'Final password for session checks'
    await page.getByLabel('New password', { exact: true }).fill(finalPassword)
    const reset = page.waitForResponse(response =>
      response.url().endsWith('/web/auth/reset') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Set password', exact: true }).click()
    expect((await reset).ok()).toBe(true)
    await expect(page.locator('.auth-form__lead')).toBeVisible()
    expect((await otherPage.request.get('/web/account')).status()).toBe(401)
    expect(otherPage.isClosed()).toBe(false)
    expect((await page.request.get('/web/account')).status()).toBe(200)
    await page.screenshot({ path: info.outputPath('reset-password.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
    await login(finalPassword)
  } finally {
    await other.close()
  }
})
