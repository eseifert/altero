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

test.describe('Shahmukhi Punjabi', () => {
  test.use({ locale: 'pa-PK' })

  test('loads the Punjabi script selected by Pakistan', async ({ page }, testInfo) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'pa-Arab')
    await expect(page.getByRole('button', { name: 'سائن ان کرو', exact: true })).toBeVisible()
    expect(await accessibilityProblems(page)).toEqual([])

    await signIn(page)
    await expect(page.getByText('میری لائبریری', { exact: true }).first()).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('punjabi-library.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  })
})

test.describe('Gurmukhi Punjabi', () => {
  test.use({ locale: 'pa-Guru-PK' })

  test('does not load a Shahmukhi translation for a different script', async ({ page }) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  })
})
