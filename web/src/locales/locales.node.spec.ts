// @vitest-environment node
//
// Reads the source tree, so it wants files rather than a DOM.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import de from './de'
import en from './en'
import es from './es'
import fr from './fr'
import ja from './ja'
import pt from './pt'

/**
 * The catalogues, against each other and against the source.
 *
 * Messages are keyed by their English text, which makes a missing translation
 * harmless -- it falls back to the key, which is the English sentence -- and a
 * *stale* one invisible: change the English and the old key keeps resolving in
 * five languages while nothing in English uses it any more. These tests are
 * what makes that visible.
 */

const CATALOGUES = { de, fr, es, pt, ja }

const SOURCE = fileURLToPath(new URL('../', import.meta.url))

/** Every `t('…')` key used anywhere in the interface. */
function usedKeys(): Set<string> {
  const keys = new Set<string>()

  const walk = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = `${directory}${entry.name}`
      if (entry.isDirectory()) {
        walk(`${path}/`)
      } else if (/\.(vue|ts)$/.test(entry.name) && !/\.spec\.ts$/.test(entry.name)) {
        const text = readFileSync(path, 'utf8')
        for (const [, key] of text.matchAll(/\bt\(\s*'((?:[^'\\]|\\.)+)'/g)) {
          keys.add(key.replace(/\\'/g, "'"))
        }
        for (const [, key] of text.matchAll(/keypath="([^"]+)"/g)) {
          keys.add(key)
        }
      }
    }
  }

  walk(SOURCE)
  return keys
}

describe.each(Object.entries(CATALOGUES))('the %s catalogue', (_name, catalogue) => {
  it('translates every message English has', () => {
    const missing = Object.keys(en).filter((key) => !(key in catalogue))

    expect(missing).toEqual([])
  })

  it('has no message English does not', () => {
    /* A leftover entry is a translation of a sentence that no longer exists,
       which reads as coverage it does not have. */
    const extra = Object.keys(catalogue).filter((key) => !(key in en))

    expect(extra).toEqual([])
  })

  it('keeps every placeholder its English carries', () => {
    /* A dropped `{count}` renders the braces as text; an invented one renders
       nothing at all. */
    const placeholders = (text: string) => (text.match(/\{[a-zA-Z]+\}/g) ?? []).sort()

    for (const [key, translated] of Object.entries(catalogue as Record<string, string>)) {
      const source = (en as Record<string, string>)[key]
      if (!source) continue
      expect(placeholders(translated), key).toEqual(placeholders(source))
    }
  })

  it('keeps both branches of a plural message', () => {
    for (const [key, translated] of Object.entries(catalogue as Record<string, string>)) {
      const source = (en as Record<string, string>)[key]
      if (!source?.includes('|')) continue
      expect(translated.split('|'), key).toHaveLength(source.split('|').length)
    }
  })
})

describe('the English catalogue', () => {
  it('holds every key the interface asks for', () => {
    const missing = [...usedKeys()].filter((key) => !(key in en)).sort()

    expect(missing).toEqual([])
  })

  it('holds nothing the interface no longer asks for', () => {
    const used = usedKeys()
    const unused = Object.keys(en).filter((key) => !used.has(key))

    expect(unused).toEqual([])
  })

  it('maps every key to itself', () => {
    const mismatched = Object.entries(en).filter(([key, value]) => key !== value)

    expect(mismatched).toEqual([])
  })
})
