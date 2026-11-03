import { accessibilityProblems, expect, signIn, state, test } from './state'

async function create(path: string, objects: unknown[]): Promise<string[]> {
  const { baseURL, key } = state()
  const response = await fetch(`${baseURL}/users/1/${path}`, {
    method: 'POST',
    headers: { 'Zotero-API-Key': key, 'Content-Type': 'application/json' },
    body: JSON.stringify(objects),
  })
  expect(response.ok).toBeTruthy()
  const result = await response.json()
  expect(result.failed).toEqual({})
  return objects.map((_, index) => result.successful[String(index)].key)
}

for (const reducedMotion of ['no-preference', 'reduce'] as const) {
  test.describe(`library motion: ${reducedMotion}`, () => {
    test.use({ reducedMotion })

    test('collection branches animate, survive interrupted toggles and release their height', async ({ page }, info) => {
      const name = `Motion ${reducedMotion} ${info.project.name}`
      const [parent] = await create('collections', [{ name }])
      const [child] = await create('collections', [{ name: `${name} child`, parentCollection: parent }])
      const [grandchild] = await create('collections', [{ name: `${name} grandchild`, parentCollection: child }])
      await signIn(page)
      const row = page.locator(`[data-drop="collection:${parent}"]`)
      const branch = row.locator('..').locator('ul.tree').first()

      // Record the actual transition classes and computed styles as Vue applies
      // them, including transitions too brief for a Playwright poll to catch.
      await row.locator('..').evaluate((element) => {
        const samples: { duration: number; height: string }[] = []
        ;(window as unknown as { branchMotion: typeof samples }).branchMotion = samples
        new MutationObserver(() => {
          const branch = element.querySelector('ul.collapse-enter-active, ul.collapse-leave-active')
          if (branch instanceof HTMLElement) {
            samples.push({ duration: parseFloat(getComputedStyle(branch).transitionDuration), height: branch.style.height })
          }
        }).observe(element, { childList: true, attributes: true, subtree: true, attributeFilter: ['class', 'style'] })
      })

      await row.getByRole('button', { name: 'Expand', exact: true }).click()
      await expect(branch).toBeVisible()
      await expect.poll(() => page.evaluate(() => (window as unknown as { branchMotion: unknown[] }).branchMotion.length)).toBeGreaterThan(0)
      const samples = await page.evaluate(() => (window as unknown as { branchMotion: { duration: number; height: string }[] }).branchMotion)
      expect(samples.some((sample) => sample.height.endsWith('px'))).toBe(true)
      expect(samples.some((sample) => reducedMotion === 'reduce' ? sample.duration <= 0.001 : sample.duration >= 0.12 && sample.duration <= 0.25)).toBe(true)
      await expect(branch).toHaveCSS('height', /[1-9][\d.]*px/)
      await expect.poll(() => branch.evaluate((element) => (element as HTMLElement).style.height)).toBe('')

      // A deeper branch must be free to grow after its parent's animation.
      await page.locator(`[data-drop="collection:${child}"]`).getByRole('button', { name: 'Expand', exact: true }).click()
      await expect(page.locator(`[data-drop="collection:${grandchild}"]`)).toBeVisible()
      await row.locator('.tree__twisty').evaluate((button: HTMLButtonElement) => {
        button.click()
        requestAnimationFrame(() => requestAnimationFrame(() => button.click()))
      })
      await expect(row.locator('.tree__twisty')).toHaveAttribute('aria-expanded', 'true')
      await expect(branch).toBeVisible()
      await expect.poll(() => branch.evaluate((element) => (element as HTMLElement).style.height)).toBe('')
      await row.getByRole('button', { name: 'Collapse', exact: true }).click()
      await expect(branch).toHaveCount(0)
      expect(await accessibilityProblems(page)).toEqual([])
    })
  })
}
