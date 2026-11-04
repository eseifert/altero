// @vitest-environment node
//
// Reads the source tree, so it wants files rather than a DOM.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import af from './af'
import ar from './ar'
import bg from './bg'
import bn from './bn'
import br from './br'
import ca from './ca'
import cs from './cs'
import da from './da'
import de from './de'
import el from './el'
import enGB from './en-GB'
import en from './en-US'
import es from './es'
import et from './et'
import eu from './eu'
import fa from './fa'
import fi from './fi'
import fr from './fr'
import gl from './gl'
import ha from './ha'
import heIL from './he-IL'
import hi from './hi'
import hr from './hr'
import hu from './hu'
import id from './id'
// `it` is vitest's, so the Italian catalogue comes in under another name and
// goes back to its tag in `CATALOGUES` below.
import icelandic from './is'
import italian from './it'
import ja from './ja'
import ka from './ka'
import km from './km'
import ko from './ko'
import lt from './lt'
import lv from './lv'
import ml from './ml'
import mn from './mn'
import nb from './nb'
import nl from './nl'
import nn from './nn'
import pl from './pl'
import paArab from './pa-Arab'
import ptBR from './pt-BR'
import ptPT from './pt-PT'
import ro from './ro'
import ru from './ru'
import sk from './sk'
import sl from './sl'
import sr from './sr'
import sv from './sv'
import sw from './sw'
import ta from './ta'
import th from './th'
import tl from './tl'
import tr from './tr'
import uk from './uk'
import ur from './ur'
import vi from './vi'
import yo from './yo'
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
  br,
  es,
  'pt-BR': ptBR,
  'pt-PT': ptPT,
  ca,
  eu,
  gl,
  it: italian,
  nl,
  af,
  sw,
  ha,
  yo,
  ar,
  fa,
  'he-IL': heIL,
  da,
  nb,
  nn,
  sv,
  is: icelandic,
  fi,
  pl,
  cs,
  sk,
  sl,
  hr,
  sr,
  hu,
  ro,
  lt,
  lv,
  et,
  ru,
  uk,
  ur,
  'pa-Arab': paArab,
  bg,
  el,
  ka,
  mn,
  tr,
  hi,
  bn,
  ta,
  ml,
  ja,
  ko,
  th,
  km,
  vi,
  id,
  tl,
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
const PLURAL_BRANCHES: Record<string, number> = {
  ar: 6, 'he-IL': 3,
  pl: 3, cs: 3, sk: 3, hr: 3, sr: 3, lt: 3, lv: 3, ro: 3, ru: 3, uk: 3,
  sl: 4, br: 5,
}

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

  if (name !== 'en-GB') {
    it('translates merge instructions instead of copying missing upstream translations', () => {
      for (const key of [
        'Merge Items',
        'Choose the version of the item to use as the master item:',
        'Select fields to keep from other versions of the item:',
        'Merged items must all be of the same item type.',
      ] as const) {
        expect(catalogue[key], key).not.toBe(key)
      }
    })
  }

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

describe.each([
  ['bg', bg, ['първи', 'последен']],
  ['ca', ca, ['primer', 'últim']],
  ['el', el, ['πρώτο', 'τελευταίο']],
  ['fi', fi, ['etu', 'suku']],
  ['ha', ha, ['na farko', 'na ƙarshe']],
  ['id', id, ['pertama', 'terakhir']],
  ['is', icelandic, ['fyrsta', 'síðasta']],
  ['pt-BR', ptBR, ['primeiro', 'último']],
  ['pt-PT', ptPT, ['primeiro', 'último']],
  ['sk', sk, ['krstné']],
  ['sw', sw, ['ya kwanza', 'ya mwisho']],
  ['ta', ta, ['முதல்', 'கடை']],
  ['th', th, ['อันดับแรก', 'อันดับสุดท้าย']],
  ['tr', tr, ['ilk', 'son']],
  ['yo', yo, ['àkọ́kọ́', 'ìkẹyìn']],
] as const)('creator names in %s', (_name, catalogue, ordinals) => {
  it('labels names rather than ordinal positions or incomplete stems', () => {
    // These hints also name the inputs to assistive technology. A bare
    // translation of “first”/“last” describes order, not a person's name.
    for (const key of ['first', 'last'] as const) {
      expect(ordinals, key).not.toContain(catalogue[key])
    }
    expect(catalogue.first).not.toBe(catalogue.last)
  })
})

describe.each([['km', km], ['th', th], ['vi', vi]] as const)('provider labels in %s', (_name, catalogue) => {
  it('adds local wording to technical identifiers used in provider setup', () => {
    for (const key of ['Client ID', 'Client secret', 'Issuer'] as const) {
      expect(catalogue[key], key).not.toBe(key)
      expect(catalogue[key], key).toContain(key)
    }
  })
})

describe('Tagalog terminology', () => {
  it.each([
    'Display name', 'Email address', 'Visibility', 'Storage', 'Migration revision',
    'Callback address', 'Client ID', 'Client secret', 'Issuer', 'Sign-on URL', 'Signing certificate',
    'Heading 1', 'Heading 2', 'Heading 3', 'Bold', 'Italic', 'Strikethrough',
  ] as const)('localizes the reviewed label “%s”', (key) => {
    expect(tl[key]).not.toBe(key)
  })

  it('uses the same library term in Undo as in the rest of the interface', () => {
    expect(tl['Undo is no longer available because the library changed.']).toContain(tl.Library.toLowerCase())
  })
})

describe('German address', () => {
  it('avoids informal pronouns and singular commands', () => {
    // Neutral instructions first; use formal Sie where direct address helps.
    // Match whole words so third-person pronouns and words like „Direkt“ pass.
    const informal = /\b(?:du|dich|dir|dein(?:e[nmsr]?|s)?|füge|gib|wähle|kopiere|lass|richte|scanne|öffne|melde|erlaube|nimm|nutze|lade|erstelle|hebe|speichere|spiele|synchronisiere|willst|benachrichtige|bestätige|mache)\b/iu
    const found = Object.entries(de).filter(([, translated]) => informal.test(translated))

    expect(found).toEqual([])
  })
})

describe('Serbian script', () => {
  it('uses Cyrillic for prose while preserving product names and protocol labels', () => {
    for (const [key, translated] of Object.entries(sr)) {
      const prose = translated
        .replace(/\{[a-zA-Z]+\}/g, '')
        .replace(/\/\.well-known\/openid-configuration/g, '')
        .replace(/\b(?:Creative Commons|OpenID Connect|HTTP-Redirect|ALTERO_PUBLIC_URL|zotero\.org|WebDAV|Zotero|altero|Yubikey|API|SAML|PEM|URL|Entity ID|ID|Issuer|Web|Settings|Security|Applications|Ctrl|Del|End|Enter|Esc|Home|Page Down|Page Up|Shift)\b/g, '')

      expect(prose, key).not.toMatch(/\p{Script=Latin}/u)
    }
  })
})

describe('Shahmukhi Punjabi', () => {
  it('uses the Arabic script throughout, without Gurmukhi characters', () => {
    for (const translated of Object.values(paArab)) {
      expect(translated).not.toMatch(/[\u0a00-\u0a7f]/u)
    }
  })
})

describe('the American English catalogue', () => {
  it('checks every catalogue in the source tree', () => {
    const tags = readdirSync(new URL('./', import.meta.url))
      .filter((name) => name.endsWith('.ts') && !name.endsWith('.spec.ts'))
      .map((name) => name.slice(0, -3))
    expect(['en-US', ...Object.keys(CATALOGUES)].sort()).toEqual(tags.sort())
  })

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
