import { accessibilityProblems, expect, signIn, test } from './state'

test.describe('Hebrew', () => {
  test.use({ locale: 'he' })

  test('resolves bare Hebrew and loads Zotero field names', async ({ page }, testInfo) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'he-IL')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    await expect(page.getByRole('button', { name: 'כניסה', exact: true })).toBeVisible()
    expect(await accessibilityProblems(page)).toEqual([])

    await signIn(page)
    await expect(page.getByText('הספרייה שלי', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'מיון לפי כותרת', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('hebrew-library.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  })
})

test.describe('Persian', () => {
  test.use({ locale: 'fa-IR' })

  test('loads Persian messages and Zotero field names', async ({ page }, testInfo) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'fa')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    await expect(page.getByRole('button', { name: 'ورود', exact: true })).toBeVisible()
    expect(await accessibilityProblems(page)).toEqual([])

    await signIn(page)
    await expect(page.getByText('کتابخانه', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'مرتب‌سازی بر اساس عنوان', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('persian-library.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  })
})

test.describe('Arabic', () => {
  test.use({ locale: 'ar-EG' })

  test('sets direction when the browser has no locale text-info method', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Intl.Locale.prototype, 'getTextInfo', {
        configurable: true,
        value: undefined,
      })
    })
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    await expect(page.getByRole('button', { name: 'تسجيل الدخول', exact: true })).toBeVisible()
  })

  test('loads Arabic messages and Zotero field names', async ({ page }, testInfo) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    await expect(page.getByRole('button', { name: 'تسجيل الدخول', exact: true })).toBeVisible()
    expect(await accessibilityProblems(page)).toEqual([])

    await signIn(page)
    await expect(page.getByText('مكتبتي', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'الترتيب حسب العنوان', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('arabic-library.png'), fullPage: true })
    expect(await accessibilityProblems(page)).toEqual([])
  })
})

test.describe('Urdu', () => {
  test.use({ locale: 'ur-PK' })

  test('loads its catalogue before sign-in and keeps it in the library', async ({ page }, testInfo) => {
    await page.goto('/app/sign-in')
    await expect(page.locator('html')).toHaveAttribute('lang', 'ur')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
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
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
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
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr')
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  })
})

test('all new account languages survive reload and override the browser', async ({ page }) => {
  test.setTimeout(60_000)
  await signIn(page)
  await page.goto('/app/settings/language')
  const language = page.getByRole('combobox').first()
  const responseForSave = () => page.waitForResponse(
    (response) => response.url().endsWith('/web/account/locale') && response.request().method() === 'PUT',
  )
  try {
    for (const [tag, save, confirmation] of [
      ['ar', 'حفظ', 'حُفظت اللغة والمنطقة الزمنية.'],
      ['fa', 'ذخیره', 'زبان و منطقهٔ زمانی ذخیره شدند.'],
      ['he-IL', 'שמירה', 'השפה ואזור הזמן נשמרו.'],
      ['ur', 'محفوظ کریں', 'زبان اور منطقۂ وقت محفوظ ہو گئے۔'],
      ['pa-Arab', 'سنبھالو', 'بولی تے ویلے دا خطہ سنبھال لیا۔'],
    ] as const) {
      await language.selectOption(tag)
      const saved = responseForSave()
      // There is one form action; its caption changes with the selected catalogue.
      await page.locator('main section.card button').click()
      expect((await saved).ok()).toBe(true)
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
      await expect(page.getByRole('button', { name: save, exact: true })).toBeVisible()
      await expect(page.locator('.section-panel__notice')).toHaveText(confirmation)
      await expect(page.locator('.section-panel__notice')).toHaveCSS('direction', 'rtl')
      await page.reload()
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
      await expect(language).toHaveValue(tag)
    }
  } finally {
    await language.selectOption('')
    const saved = responseForSave()
    await page.locator('main section.card button').click()
    expect((await saved).ok()).toBe(true)
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr')
    await expect(page.locator('.section-panel__notice')).toHaveText('Language and time zone saved.')
    await expect(page.locator('.section-panel__notice')).toHaveCSS('direction', 'ltr')
  }
})
