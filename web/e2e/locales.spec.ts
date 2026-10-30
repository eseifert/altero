import { accessibilityProblems, expect, signIn, test } from './state'

test.describe('Urdu', () => {
  test.use({ locale: 'ur-PK' })

  test('loads its catalogue before sign-in and keeps it in the library', async ({ page }, testInfo) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'ur')
    await expect(page.getByRole('button', { name: 'سائن ان کریں', exact: true })).toBeVisible()
    expect(await accessibilityProblems(page)).toEqual([])

    await signIn(page)
    await expect(page.getByText('میرا کتب خانہ', { exact: true }).first()).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('lang', 'ur')
    await page.screenshot({ path: testInfo.outputPath('urdu-library.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  })
})
