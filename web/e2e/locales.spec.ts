import { accessibilityProblems, expect, signIn, test } from './state'

test.describe('browser locale resolution', () => {
  test.use({ locale: 'pa-Guru-PK' })

  test('falls back rather than substituting a different script', async ({ page }) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr')
  })
})

test.describe('direction fallback', () => {
  test.use({ locale: 'ar-EG' })

  test('sets direction without the optional browser text-info method', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Intl.Locale.prototype, 'getTextInfo', {
        configurable: true, value: undefined,
      })
    })
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    expect(await accessibilityProblems(page)).toEqual([])
  })
})

test.describe('account locale preferences', () => {
  test.use({ locale: 'fr-CA' })

  test('persists an account override and returns to the browser preference', async ({ page }) => {
    await signIn(page)
    await expect(page.locator('html')).toHaveAttribute('lang', 'fr')
    await page.goto('/app/settings/language')
    const language = page.getByRole('combobox').first()
    const save = async (tag: string, resolved: string, direction: string) => {
      await language.selectOption(tag)
      const saved = page.waitForResponse(response =>
        response.url().endsWith('/web/account/locale') && response.request().method() === 'PUT',
      )
      await page.locator('main section.card button').click()
      expect((await saved).ok()).toBe(true)
      await expect(page.locator('html')).toHaveAttribute('lang', resolved)
      await expect(page.locator('html')).toHaveAttribute('dir', direction)
      await expect(page.locator('.section-panel__notice')).toBeVisible()
      await expect(page.locator('.section-panel__notice')).toHaveCSS('direction', direction)
    }
    try {
      await save('ar', 'ar', 'rtl')
      await page.reload()
      await expect(page.locator('html')).toHaveAttribute('lang', 'ar')
      await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
      await expect(language).toHaveValue('ar')
      expect(await accessibilityProblems(page)).toEqual([])
    } finally {
      await save('', 'fr', 'ltr')
    }
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('lang', 'fr')
    await expect(language).toHaveValue('')
  })
})
