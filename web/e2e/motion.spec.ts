import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

interface DialogMotion {
  phase: string
  duration: number
  modal: boolean
  transform: string
  panelTransform: string
}

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

    test('item, note and attachment details fade in quickly and reopen cleanly', async ({ page }, info) => {
      const title = `Detail motion ${reducedMotion} ${info.project.name}`
      const titles = [`Book ${title}`, `Note ${title}`, `Attachment ${title}`] as const
      await create('items', [
        { itemType: 'book', title: titles[0] },
        { itemType: 'note', note: `<p>${titles[1]}</p>` },
        { itemType: 'attachment', linkMode: 'linked_url', title: titles[2], url: 'https://example.org/' },
      ])
      await signIn(page)
      await page.evaluate(() => {
        const samples: { duration: number; name: string; opacity: unknown[] }[] = []
        ;(window as unknown as { detailMotion: typeof samples }).detailMotion = samples
        new MutationObserver((records) => {
          for (const record of records) for (const node of record.addedNodes) {
            if (!(node instanceof HTMLElement)) continue
            const pane = node.matches('.library__detail') ? node : node.querySelector('.library__detail')
            if (!pane) continue
            const style = getComputedStyle(pane)
            const effect = pane.getAnimations()[0]?.effect
            samples.push({ duration: parseFloat(style.animationDuration), name: style.animationName,
              opacity: effect instanceof KeyframeEffect ? effect.getKeyframes().map((frame) => frame.opacity) : [],
            })
          }
        }).observe(document.body, { childList: true, subtree: true })
      })
      for (const title of [...titles, titles[0]]) {
        await openItem(page, title)
        await expect(page.locator('.detail__title')).toHaveText(title)
        await expect(page.locator('.library__detail')).toHaveCSS('opacity', '1')
        await page.locator('.detail__close').click()
        await expect(page.locator('.library__detail')).toHaveCount(0)
      }
      const samples = await page.evaluate(() => (window as unknown as {
        detailMotion: { duration: number; name: string; opacity: unknown[] }[]
      }).detailMotion)
      expect(samples).toHaveLength(4)
      for (const sample of samples) {
        expect(sample.name).not.toBe('none')
        if (reducedMotion === 'reduce') expect(sample.duration).toBeLessThanOrEqual(0.001)
        else {
          expect(sample.duration).toBeGreaterThanOrEqual(0.12)
          expect(sample.duration).toBeLessThanOrEqual(0.2)
          expect(sample.opacity).toEqual(['0', '1'])
        }
      }
      expect(await accessibilityProblems(page)).toEqual([])
    })

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

    for (const native of [true, false]) {
      test(`dialogs fade with focus restored and replacement focus preserved (${native ? 'native' : 'fallback'})`, async ({ page }, info) => {
        if (!native) {
          await page.addInitScript(() => {
            // Exercise the interface's older-Safari path in the real browser.
            // @ts-expect-error -- deliberately remove the native modal API.
            delete HTMLDialogElement.prototype.showModal
          })
        }
        const name = `Dialog ${native} ${reducedMotion} ${info.project.name}`
        const [collection] = await create('collections', [{ name }, { name: `${name} ${'W'.repeat(80)}` }])
        await signIn(page)
        await page.evaluate(() => {
          const samples: DialogMotion[] = []
          ;(window as unknown as { dialogMotion: typeof samples }).dialogMotion = samples
          new MutationObserver((records) => {
            for (const record of records) {
              const element = record.target
              if (!(element instanceof HTMLDialogElement)) continue
              for (const phase of ['enter', 'leave']) {
                if (element.classList.contains(`fade-scale-${phase}-active`)) {
                  samples.push({
                    phase,
                    duration: parseFloat(getComputedStyle(element).transitionDuration),
                    modal: element.matches(':modal') || element.hasAttribute('data-modal-fallback'),
                    transform: getComputedStyle(element).transform,
                    panelTransform: getComputedStyle(element.firstElementChild!).transform,
                  })
                }
              }
            }
          }).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] })
        })
        const opener = page.getByRole('button', { name: 'New collection', exact: true })
        await expect(opener).toBeVisible()
        await page.evaluate(() => document.fonts.ready)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
        await opener.click()
        const dialog = page.getByRole('dialog', { name: 'New collection', exact: true })
        const field = dialog.getByRole('textbox')
        await expect(field).toBeFocused()
        await dialog.getByRole('button', { name: 'Create', exact: true }).focus()
        await page.keyboard.press('Tab')
        if (native) {
          // Native dialogs may let Tab reach the browser's own chrome.
          expect(await dialog.evaluate((element) => document.activeElement === document.body || element.contains(document.activeElement))).toBe(true)
          await field.focus()
        } else await expect(field).toBeFocused()
        await page.keyboard.press('Escape')
        await expect(dialog).toHaveCount(0)
        await expect(opener).toBeFocused()
        const samples = await page.evaluate(() => (window as unknown as { dialogMotion: DialogMotion[] }).dialogMotion)
        for (const phase of ['enter', 'leave']) {
          expect(samples.some((sample) => sample.phase === phase && sample.modal && (reducedMotion === 'reduce' ? sample.duration <= 0.001 : sample.duration >= 0.12 && sample.duration <= 0.24))).toBe(true)
        }
        if (!native) {
          expect(samples.every((sample) => sample.transform === 'none')).toBe(true)
          expect(samples.some((sample) => sample.panelTransform !== 'none')).toBe(true)
        }

        // Changing directly from collection settings to sharing must not let
        // the old dialog steal focus or unlock scrolling under the new one.
        await page.locator(`[data-drop="collection:${collection}"]`).getByRole('button', { name: `Settings for “${name}”`, exact: true }).click()
        await page.getByRole('dialog').getByRole('button', { name: 'Share a link…', exact: true }).click()
        const share = page.getByRole('dialog', { name: 'Share this collection', exact: true })
        await expect(share).toBeVisible()
        await expect(page.locator('dialog')).toHaveCount(1)
        expect(await share.evaluate((element) => element.contains(document.activeElement))).toBe(true)
        if (!native) await expect(page.locator('body')).toHaveCSS('overflow', 'hidden')
        await share.getByRole('button', { name: 'Cancel', exact: true }).click()
        await expect(page.locator('dialog')).toHaveCount(0)
        if (!native) await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden')
        expect(await accessibilityProblems(page)).toEqual([])
      })
    }
  })
}
