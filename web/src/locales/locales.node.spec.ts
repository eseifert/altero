// @vitest-environment node
//
// Reads the source tree, so it wants files rather than a DOM.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import da from './da'
import de from './de'
import enGB from './en-GB'
import en from './en-US'
import es from './es'
import fr from './fr'
// `it` is vitest's, so the Italian catalogue comes in under another name and
// goes back to its tag in `CATALOGUES` below.
import italian from './it'
import ja from './ja'
import nl from './nl'
import pl from './pl'
import ptBR from './pt-BR'
import ptPT from './pt-PT'
import ru from './ru'
import zhCN from './zh-CN'
import zhTW from './zh-TW'

/**
 * The catalogues, against each other and against the source.
 *
 * Messages are keyed by their English text, which makes a missing translation
 * harmless -- it falls back to the key, which is the English sentence -- and a
 * *stale* one invisible: change the English and the old key keeps resolving in
 * five languages while nothing in English uses it any more. These tests are
 * what makes that visible.
 */

const CATALOGUES = {
  'en-GB': enGB,
  de,
  fr,
  es,
  'pt-BR': ptBR,
  'pt-PT': ptPT,
  it: italian,
  nl,
  da,
  pl,
  ru,
  ja,
  'zh-CN': zhCN,
  'zh-TW': zhTW,
}

/**
 * How many branches a plural message has, where that is not English's two.
 *
 * The same table as `PLURAL_RULES` in `i18n.ts`, from the other side: there it
 * decides which branch to render, here it holds a catalogue to writing all of
 * them. A Polish message with two branches would render "2 elementów" and
 * never fail a test that only counted English's forms.
 */
const PLURAL_BRANCHES: Record<string, number> = { pl: 3, ru: 3 }

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

describe.each(Object.entries(CATALOGUES))('the %s catalogue', (name, catalogue) => {
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
       nothing at all. Branch by branch rather than over the whole message,
       because a language with a third plural form has a third `{count}` and
       counting them all would call that a mismatch. A branch past English's
       last is held to that last one, every branch of a plural carrying the
       same placeholders. */
    const placeholders = (text: string) => (text.match(/\{[a-zA-Z]+\}/g) ?? []).sort()

    for (const [key, translated] of Object.entries(catalogue as Record<string, string>)) {
      const source = (en as Record<string, string>)[key]
      if (!source) continue
      const wanted = source.split('|').map(placeholders)
      translated.split('|').forEach((branch, index) => {
        expect(placeholders(branch), key).toEqual(wanted[Math.min(index, wanted.length - 1)])
      })
    }
  })

  it('writes a branch for every plural form its own language has', () => {
    const branches = PLURAL_BRANCHES[name] ?? 2

    for (const [key, translated] of Object.entries(catalogue as Record<string, string>)) {
      const source = (en as Record<string, string>)[key]
      if (!source?.includes('|')) continue
      expect(translated.split('|'), key).toHaveLength(branches)
    }
  })

  it('splits nothing English keeps whole', () => {
    /* A stray `|` in a message that is not a plural renders as two branches,
       one of which is never shown. */
    for (const [key, translated] of Object.entries(catalogue as Record<string, string>)) {
      const source = (en as Record<string, string>)[key]
      if (!source || source.includes('|')) continue
      expect(translated, key).not.toContain('|')
    }
  })
})

describe('the American English catalogue', () => {
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
