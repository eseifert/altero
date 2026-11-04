import { accessibilityProblems, expect, signIn, test } from './state'

for (const [tag, issuer, client, secret] of [
  ['km', 'អ្នកចេញ (Issuer)', 'លេខសម្គាល់កម្មវិធី (Client ID)', 'សោសម្ងាត់កម្មវិធី (Client secret)'],
  ['th', 'ผู้ออก (Issuer)', 'รหัสไคลเอ็นต์ (Client ID)', 'ข้อมูลลับไคลเอ็นต์ (Client secret)'],
  ['vi', 'Bên phát hành (Issuer)', 'Mã ứng dụng khách (Client ID)', 'Mã bí mật ứng dụng khách (Client secret)'],
  ['tl', 'Tagapag-isyu (Issuer)', 'ID ng application (Client ID)', 'Lihim ng application (Client secret)'],
] as const) {
  test.describe(`provider labels in ${tag}`, () => {
    test.use({ locale: tag })

    test('labels the OpenID Connect fields in the local language', async ({ page }, info) => {
      await signIn(page)
      await page.goto('/app/admin/providers')
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await page.getByRole('button', { name: /OpenID Connect/ }).click()
      await page.getByRole('textbox', { name: issuer, exact: true }).fill('https://id.example.org')
      await page.getByRole('textbox', { name: client, exact: true }).fill('example-client')
      const credential = page.getByLabel(secret, { exact: true })
      await expect(credential).toHaveAttribute('type', 'password')
      await credential.fill('example-secret')
      await expect(page.getByRole('textbox', { name: issuer, exact: true })).toHaveValue('https://id.example.org')
      await expect(page.getByRole('textbox', { name: client, exact: true })).toHaveValue('example-client')
      await expect(credential).toHaveValue('example-secret')
      await page.screenshot({ path: info.outputPath(`${tag}-provider.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
    })
  })
}
