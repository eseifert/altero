import { accessibilityProblems, expect, PASSWORD, signIn, test } from './state'

test('key activity stays inside the card and leaves its controls reachable', async ({ page }, info) => {
  await signIn(page)
  await page.goto('/app/settings/keys')
  // Seeding already used the CLI key, including its address and user agent.
  const usage = page.locator('.settings__usage').filter({ hasText: 'Last used' }).first()
  await expect(usage).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
  const fits = await usage.evaluate((element) => {
    const line = element.getBoundingClientRect()
    const card = element.closest('.card')!.getBoundingClientRect()
    return line.left >= card.left && line.right <= card.right
  })
  expect(fits).toBe(true)
  await page.locator('summary').filter({ hasText: 'Create a key' }).click()
  await page.getByRole('textbox', { name: 'What is it for?' }).fill(`Viewport check ${info.project.name}`)
  await page.getByLabel('Current password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Create key', exact: true }).click()
  await expect(page.locator('.settings__issued')).toBeVisible()
  expect(await accessibilityProblems(page)).toEqual([])
})
