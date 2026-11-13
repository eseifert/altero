import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { BASE, PASSWORD, restart, state } from './setup'

async function apply(page: Page, username = 'applicant-' + randomUUID().slice(0, 8)) {
  const email = `${username}@example.org`
  await page.goto('/app/register')
  await expect(page.getByRole('heading', { name: 'Request an account', exact: true })).toBeVisible()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await page.locator('input[autocomplete=username]').fill(username)
  await page.locator('input[type=email]').fill(email)
  await page.getByRole('button', { name: 'Request an account', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  const letters = () => readFileSync(join(state().directory, 'mail.jsonl'), 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line) as string)
  await expect.poll(() => letters().some((mail) => mail.includes(email))).toBe(true)
  const letter = letters().find((mail) => mail.includes(email))!
  const link = letter.match(/http:\/\/127\.0\.0\.1:8767\/app\/registration#token=[\w-]+/)?.[0]
  expect(link).toBeTruthy()
  await page.goto(link!)
  await expect(page.getByRole('button', { name: 'Confirm your email address', exact: true })).toBeVisible()
  await expect.poll(() => page.url().includes('#token')).toBe(false)
  await page.getByRole('button', { name: 'Confirm your email address', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Awaiting administrator approval' })).toBeVisible()
  return { username, email, link: link! }
}
async function review(page: Page, email: string, decision: 'Approve' | 'Reject') {
  await page.goto('/app/sign-in')
  await page.locator('input[autocomplete=username]').fill('operator')
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/app\/library/)
  await page.goto('/app/admin/registrations')
  const row = page.locator('li').filter({ has: page.getByText(email, { exact: true }) })
  await row.getByRole('button', { name: 'Review', exact: true }).click()
  // This fixture administrator has a password and no recent proof. The field
  // appears only after the real proof request completes; count() cannot wait.
  if (decision === 'Approve') {
    await row.getByLabel('Confirm your password', { exact: true }).fill(PASSWORD)
  }
  await row.getByRole('button', { name: decision, exact: true }).click()
  await expect(row).toHaveCount(0)
}
async function signIn(page: Page, username: string, password: string) {
  await page.goto('/app/sign-in')
  await page.locator('input[autocomplete=username]').fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/app\/library/)
}

test('mailbox proof, restart, review and enrollment lead to an ordinary account', async ({ page, browser }, info) => {
  const applicant = await apply(page)
  expect((await page.request.get('/web/libraries')).status()).toBe(401)
  await expect(new AxeBuilder({ page }).analyze()).resolves.toMatchObject({ violations: [] })
  await restart()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Awaiting administrator approval' })).toBeVisible()
  const admin = await browser.newContext({ baseURL: BASE })
  // Keep the real proof response, but make its arrival reliably asynchronous.
  // The review helper must wait for the password field rather than sample it.
  await admin.route('**/web/account/proof', async (route) => {
    const response = await route.fetch()
    await new Promise((done) => setTimeout(done, 300))
    await route.fulfill({ response })
  })
  try { await review(await admin.newPage(), applicant.email, 'Approve') } finally { await admin.close() }
  await page.getByRole('button', { name: 'Check status', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Choose your password' })).toBeVisible()
  const password = 'a personal browser acceptance passphrase'
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByLabel('Repeat password', { exact: true }).fill(password)
  await expect(new AxeBuilder({ page }).analyze()).resolves.toMatchObject({ violations: [] })
  await page.screenshot({ path: info.outputPath('approved.png'), fullPage: true })
  await page.getByRole('button', { name: 'Set password', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your account is ready' })).toBeVisible()
  expect((await page.request.get('/web/auth/session')).status()).toBe(401)
  await signIn(page, applicant.username, password)
})

test('rejection remains visible and a used mailbox proof cannot be replayed', async ({ page, browser }) => {
  const applicant = await apply(page)
  const admin = await browser.newContext({ baseURL: BASE })
  try { await review(await admin.newPage(), applicant.email, 'Reject') } finally { await admin.close() }
  await page.getByRole('button', { name: 'Check status', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your request was rejected' })).toBeVisible()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await page.goto(applicant.link)
  await page.getByRole('button', { name: 'Confirm your email address', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
})

test('a committed password survives a lost enrollment response and server restart', async ({ page, browser }) => {
  const applicant = await apply(page)
  const admin = await browser.newContext({ baseURL: BASE })
  try { await review(await admin.newPage(), applicant.email, 'Approve') } finally { await admin.close() }
  await page.getByRole('button', { name: 'Check status', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Choose your password' })).toBeVisible()
  const password = 'a recoverable committed browser passphrase'
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByLabel('Repeat password', { exact: true }).fill(password)
  await page.route('**/web/registration/enroll', async (route) => {
    expect((await route.fetch()).status()).toBe(200)
    await route.abort('failed')
  })
  await page.getByRole('button', { name: 'Set password', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await restart()
  await page.unroute('**/web/registration/enroll')
  await signIn(page, applicant.username, password)
})


test.describe('right-to-left applicant layout', () => {
  test.use({ locale: 'ar-EG' })
  test('cancellation preserves a readable status without granting account access', async ({ page }, info) => {
    await apply(page)
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    await page.getByRole('button', { name: 'Cancel request', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Your request was cancelled' })).toBeVisible()
    expect((await page.request.get('/web/auth/session')).status()).toBe(401)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect(new AxeBuilder({ page }).analyze()).resolves.toMatchObject({ violations: [] })
    await page.screenshot({ path: info.outputPath('cancelled-rtl.png'), fullPage: true })
  })
})


test('a refused SMTP recipient remains recoverable without resetting durable mail limits', async ({ page }) => {
  test.setTimeout(120000)
  const username = 'fail-' + randomUUID().slice(0, 8)
  const email = `${username}@example.org`
  await page.goto('/app/register')
  await page.locator('input[autocomplete=username]').fill(username)
  await page.locator('input[type=email]').fill(email)
  await page.getByRole('button', { name: 'Request an account', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  expect(readFileSync(join(state().directory, 'mail.jsonl'), 'utf8')).not.toContain(email)
  await restart()
  const limited = await page.request.post('/web/registration/apply', { data: { username, email } })
  expect(limited.status()).toBe(429)
  const wait = Number(limited.headers()['retry-after'])
  expect(wait).toBeGreaterThan(0)
  expect(wait).toBeLessThanOrEqual(60)
  // This is the server's actual protocol budget, rather than a UI settling delay.
  await page.waitForTimeout((wait + 1) * 1000)
  const resumed = await apply(page, username)
  expect(resumed.email).toBe(email)
  expect((await page.request.get('/web/auth/session')).status()).toBe(401)
})
