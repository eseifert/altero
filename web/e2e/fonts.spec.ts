import { expect, test } from './state'
import { readFileSync } from 'node:fs'

const SAMPLES = [
  ['ar-EG', 'ar', 'IBM Plex Sans Arabic', 'العربية'],
  ['fa-IR', 'fa', 'IBM Plex Sans Arabic', 'پچژگکی'],
  ['he-IL', 'he-IL', 'IBM Plex Sans Hebrew', 'עברית'],
  ['ur-PK', 'ur', 'IBM Plex Sans Arabic', 'ٹڈڑںھہے'],
  ['pa-PK', 'pa-Arab', 'IBM Plex Sans Arabic', 'پنجابیݨ'],
] as const

for (const [locale, tag, family, example] of SAMPLES) {
  const source = readFileSync(new URL(`../src/locales/${tag}.ts`, import.meta.url), 'utf8')
  const script = tag === 'he-IL' ? /\p{Script=Hebrew}/u : /\p{Script=Arabic}/u
  // Include every script letter used by the catalogue, not only the examples.
  const letters = [...new Set([...source].filter(letter => /\p{L}/u.test(letter) && script.test(letter)))].join('')
  const sample = example + letters
  test.describe(`${tag} local fonts`, () => {
    test.use({ locale })

    test('renders every sample glyph with the shipped font at all UI weights', async ({ page, context }, info) => {
      const fontRequests: string[] = []
      page.on('request', request => {
        if (request.resourceType() === 'font') fontRequests.push(request.url())
      })
      await page.goto('/app/sign-in')
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
      await expect.poll(() => page.evaluate(family => Array.from(document.fonts)
        .some(face => face.family.replaceAll(/["']/g, '') === family), family),
      { message: `deferred ${family} faces are registered` }).toBe(true)
      await page.evaluate(async ({ family, sample }) => {
        for (const weight of [400, 500, 700]) {
          const text = document.createElement('p')
          text.id = `font-proof-${weight}`
          text.dir = 'auto'
          text.textContent = sample
          text.style.fontWeight = String(weight)
          text.style.overflowWrap = 'anywhere'
          document.querySelector('.auth-form')!.append(text)
          await document.fonts.load(`${weight} 24px "${family}"`, sample)
        }
        await document.fonts.ready
      }, { family, sample })

      // FontFaceSet.check alone can pass while a fallback draws missing glyphs.
      // Chromium reports the fonts that actually painted these text nodes.
      const session = await context.newCDPSession(page)
      await session.send('DOM.enable')
      await session.send('CSS.enable')
      const { root } = await session.send('DOM.getDocument')
      // PostScript names read from IBM's font name tables: Regular has no
      // suffix and Medium is abbreviated, unlike the package filenames.
      for (const [weight, suffix] of [[400, ''], [500, '-Medm'], [700, '-Bold']] as const) {
        const { nodeId } = await session.send('DOM.querySelector', { nodeId: root.nodeId, selector: `#font-proof-${weight}` })
        const { fonts } = await session.send('CSS.getPlatformFontsForNode', { nodeId })
        expect(fonts.map(font => font.postScriptName), `${tag} weight ${weight}: ${sample}`)
          .toEqual([`${family.replaceAll(' ', '')}${suffix}`])
        expect(fonts.every(font => font.isCustomFont && font.glyphCount > 0)).toBe(true)
      }
      const faces = await page.evaluate(family => Array.from(document.fonts)
        .filter(face => face.family.replaceAll(/["']/g, '') === family)
        .map(face => face.display), family)
      expect(faces).toEqual(['swap', 'swap', 'swap'])
      expect(fontRequests.length).toBeGreaterThan(0)
      const origin = new URL(page.url()).origin
      for (const url of fontRequests) {
        expect(new URL(url).origin).toBe(origin)
        expect(new URL(url).pathname).toMatch(/^\/app\/assets\/.+\.woff2$/)
      }
      await page.screenshot({ path: info.outputPath(`${tag}-fonts.png`), fullPage: true })
      await session.detach()
    })
  })
}

test('an English page fetches no Arabic or Hebrew font files', async ({ page }) => {
  const fonts: string[] = []
  page.on('request', request => {
    if (request.resourceType() === 'font') fonts.push(request.url())
  })
  await page.goto('/app/sign-in')
  await page.waitForFunction(() => Array.from(document.fonts).some(face => face.family.includes('Arabic')))
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  expect(fonts.filter(url => /IBMPlexSans(Arabic|Hebrew)/.test(url))).toEqual([])
})
