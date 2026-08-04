// @vitest-environment node
//
// Reads the stylesheets from disk, so it wants files rather than a DOM.
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import postcss from 'postcss'
import { describe, expect, it } from 'vitest'

import config, { swapFontDisplay } from '../../vite.config'

const HERE = fileURLToPath(new URL('./', import.meta.url))
const WEB = fileURLToPath(new URL('../../', import.meta.url))

const TOKENS = readFileSync(`${HERE}tokens.css`, 'utf8')
const FONTS = readFileSync(`${HERE}fonts.css`, 'utf8')

/** Every stylesheet and template that could name a font, read as text. */
function stylesheets(): [string, string][] {
  const files: [string, string][] = [['index.html', readFileSync(`${WEB}index.html`, 'utf8')]]

  const walk = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = `${directory}${entry.name}`
      if (entry.isDirectory()) walk(`${path}/`)
      else if (/\.(css|vue|html)$/.test(entry.name)) files.push([path, readFileSync(path, 'utf8')])
    }
  }

  walk(`${WEB}src/`)
  return files
}

describe('the type stack', () => {
  it('asks for Plex first, and for the Japanese cut behind it', () => {
    const [, stack] = TOKENS.match(/--md-sys-typescale-font:\s*([^;]+);/) ?? []

    expect(stack).toBeDefined()
    const families = stack.split(',').map((name) => name.trim().replace(/^'|'$/g, ''))
    expect(families.slice(0, 2)).toEqual(['IBM Plex Sans', 'IBM Plex Sans JP'])
  })

  it('keeps a system fallback, which is what is on screen while Plex loads', () => {
    expect(TOKENS).toMatch(/--md-sys-typescale-font:[^;]*system-ui/)
    expect(TOKENS).toMatch(/--md-sys-typescale-font:[^;]*sans-serif;/)
  })
})

describe('where the faces come from', () => {
  it('is this application and nowhere else', () => {
    /* A font fetched from a CDN tells that CDN who is reading a library, and
       stops working when it is unreachable. The build rewrites the packages'
       own relative URLs to assets of ours; an absolute one would escape that. */
    for (const [path, text] of stylesheets()) {
      expect(text.match(/url\(\s*['"]?https?:/g) ?? [], path).toEqual([])
      expect(text.match(/fonts\.(googleapis|gstatic|bunny)/g) ?? [], path).toEqual([])
    }
  })

  it('is the packages the build installs, not a copy that can drift', () => {
    const imported = [...FONTS.matchAll(/@import\s+'([^']+)'/g)].map(([, path]) => path)

    expect(imported.length).toBeGreaterThan(0)
    for (const path of imported) {
      expect(path).toMatch(/^@ibm\/plex-sans(-jp)?\/fonts\/split\//)
    }
  })
})

describe('font-display', () => {
  const run = (css: string) => postcss([swapFontDisplay]).process(css, { from: undefined }).css

  it('is swap on a face that does not say, so no text waits on a download', () => {
    const css = run("@font-face { font-family: 'IBM Plex Sans'; src: url(a.woff2); }")

    expect(css).toContain('font-display: swap')
  })

  it('is applied by the build, not merely available to it', () => {
    const plugins = (config as { css?: { postcss?: { plugins?: unknown[] } } }).css?.postcss?.plugins

    expect(plugins).toContain(swapFontDisplay)
  })

  it('leaves a face that has already decided alone', () => {
    const css = run("@font-face { font-family: 'X'; font-display: block; src: url(a.woff2); }")

    expect(css).toContain('font-display: block')
    expect(css).not.toContain('swap')
  })
})
