// @vitest-environment node
//
// Reads the stylesheets from disk, so it wants files rather than a DOM.
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import postcss from 'postcss'
import { describe, expect, it } from 'vitest'

import config, { swapFontDisplay } from '../../vite.config'

const HERE = fileURLToPath(new URL('./', import.meta.url))
const WEB = fileURLToPath(new URL('../../', import.meta.url))

const TOKENS = readFileSync(`${HERE}tokens.css`, 'utf8')
const FONTS = readFileSync(`${HERE}fonts.css`, 'utf8') + readFileSync(`${HERE}fonts-jp.css`, 'utf8')
const RTL = existsSync(`${HERE}fonts-rtl.css`) ? readFileSync(`${HERE}fonts-rtl.css`, 'utf8') : ''

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
  it('asks for Plex first, with Japanese, Arabic and Hebrew before the system fallback', () => {
    const [, stack] = TOKENS.match(/--md-sys-typescale-font:\s*([^;]+);/) ?? []

    expect(stack).toBeDefined()
    const families = stack.split(',').map((name) => name.trim().replace(/^'|'$/g, ''))
    expect(families.slice(0, 4)).toEqual([
      'IBM Plex Sans', 'IBM Plex Sans JP', 'IBM Plex Sans Arabic', 'IBM Plex Sans Hebrew',
    ])
  })

  it('keeps a system fallback, which is what is on screen while Plex loads', () => {
    expect(TOKENS).toMatch(/--md-sys-typescale-font:[^;]*system-ui/)
    expect(TOKENS).toMatch(/--md-sys-typescale-font:[^;]*sans-serif;/)
  })
})

describe('where the faces come from', () => {
  it('loads the RTL faces through a separate dynamic stylesheet', () => {
    const main = readFileSync(`${WEB}src/main.ts`, 'utf8')
    expect(main).toContain("void import('./styles/fonts-rtl.css')")
    expect(main).not.toMatch(/^import ['"].*fonts-rtl\.css['"]/m)
  })

  it('ships regular, medium and bold RTL faces from the installed packages', () => {
    const faces: { family: string; weight: string; source: string }[] = []
    postcss.parse(RTL).walkAtRules('font-face', rule => {
      const declarations = Object.fromEntries(
        (rule.nodes ?? []).filter(node => node.type === 'decl').map(node => [node.prop, node.value]),
      )
      faces.push({ family: declarations['font-family']!, weight: declarations['font-weight']!, source: declarations.src! })
    })
    expect(faces.map(face => [face.family, face.weight])).toEqual([
      ["'IBM Plex Sans Arabic'", '400'], ["'IBM Plex Sans Arabic'", '500'], ["'IBM Plex Sans Arabic'", '700'],
      ["'IBM Plex Sans Hebrew'", '400'], ["'IBM Plex Sans Hebrew'", '500'], ["'IBM Plex Sans Hebrew'", '700'],
    ])
    for (const face of faces) {
      const path = face.source.match(/url\('([^']+)'\) format\('woff2'\)/)?.[1]
      expect(path).toMatch(/^@ibm\/plex-sans-(arabic|hebrew)\/fonts\/complete\/woff2\//)
      expect(existsSync(`${WEB}node_modules/${path}`), path).toBe(true)
    }
  })

  it('prevents font package installation hooks from reporting telemetry', () => {
    expect(readFileSync(`${WEB}.npmrc`, 'utf8')).toMatch(/^ignore-scripts=true$/m)
  })

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
