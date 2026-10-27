// @vitest-environment node
/*
 * The installed application's manifest and icons, as the build serves them.
 *
 * A node spec rather than a jsdom one: it reads the files in `public/` and
 * the PNG headers, which is what a browser deciding whether the app can be
 * installed reads too.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { CHROME_COLORS } from './themecolors'

const PUBLIC = join(import.meta.dirname, '..', 'public')

interface Manifest {
  name: string
  short_name: string
  id: string
  start_url: string
  scope: string
  display: string
  theme_color: string
  background_color: string
  icons: { src: string; sizes: string; type: string; purpose: string }[]
}

const manifest = JSON.parse(readFileSync(join(PUBLIC, 'manifest.webmanifest'), 'utf8')) as Manifest

/** A PNG's width and height, from its IHDR chunk. */
function dimensions(file: string): [number, number] {
  const bytes = readFileSync(join(PUBLIC, file))
  expect(bytes.subarray(1, 4).toString('latin1')).toBe('PNG')
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)]
}

describe('the web app manifest', () => {
  it('opens the interface on its own, inside the scope it is served from', () => {
    expect(manifest.start_url).toBe('/app/')
    expect(manifest.scope).toBe('/app/')
    expect(manifest.id).toBe('/app/')
    expect(manifest.display).toBe('standalone')
    expect(manifest.name).toBe('altero')
  })

  it('paints its bar the colour the light page’s header is', () => {
    expect(manifest.theme_color).toBe(CHROME_COLORS.light)
  })

  it('names icons that exist, at the sizes it says', () => {
    for (const icon of manifest.icons) {
      const [size] = icon.sizes.split('x').map(Number)
      expect(dimensions(icon.src)).toEqual([size, size])
      expect(icon.type).toBe('image/png')
    }
  })

  it('has the two sizes browsers ask for, and a maskable one', () => {
    expect(manifest.icons.map((icon) => icon.sizes)).toEqual(expect.arrayContaining(['192x192', '512x512']))
    expect(manifest.icons.some((icon) => icon.purpose === 'maskable')).toBe(true)
  })

  it('gives iOS its touch icon, which it takes at 180 pixels', () => {
    expect(dimensions('apple-touch-icon.png')).toEqual([180, 180])
  })
})
