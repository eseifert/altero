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

describe('Dutch address and library terms', () => {
  it('keeps the established formal address in consent and account instructions', () => {
    const informal = /\b(?:je|jij|jou|jouw)\b/iu
    expect(Object.entries(nl).filter(([, translated]) => informal.test(translated))).toEqual([])
  })

  it('uses the same note term for permissions and library controls', () => {
    for (const key of ['Read your notes', 'It cannot read your library, your notes or your attachments.'] as const) {
      expect(nl[key].toLowerCase()).toContain(nl.Notes.toLowerCase())
    }
  })

  it('names the master item consistently in merge instructions', () => {
    expect(nl['Choose the version of the item to use as the master item:'].toLowerCase()).toContain(nl['Master item'].toLowerCase())
  })
})

describe('Spanish address', () => {
  it('uses formal address rather than informal pronouns', () => {
    const informal = /(?<!\p{L})(?:tú|tu|tus|te|ti|contigo|tuyo|tuya|tuyos|tuyas)(?!\p{L})/iu
    expect(Object.entries(es).filter(([, translated]) => informal.test(translated))).toEqual([])
  })

  it('keeps second-person verbs in the formal form', () => {
    const informal = /(?<!\p{L})(?:puedes|tienes|editabas|quieres|pertenezcas|elijas|dejes|añadas|incluyas|hayas|tengas|digas|sigues|elimines)(?!\p{L})/iu
    expect(Object.entries(es).filter(([, translated]) => informal.test(translated))).toEqual([])
  })

  it('uses formal imperatives in direct instructions', () => {
    // These forms are unambiguous in the reviewed instructions. Keep third-
    // person descriptions such as “Deja de funcionar”, “pide un código” and
    // “crea una clave”. Ambiguous verbs cannot be banned catalog-wide.
    const informal = /(?<!\p{L})(?:selecciona|escribe|escanea|repite|abre|añade|elige|apunta|sincroniza|dales|cópialo|cópiala|acéptalo|permítele|guárdala|guárdalo|restáuralo|déjalo|indícalo|pégala|revísala|inténtalo|súbelos)(?!\p{L})/iu
    expect(Object.entries(es).filter(([, translated]) => informal.test(translated))).toEqual([])
  })

  it('uses the master-item label in merge instructions', () => {
    expect(es['Choose the version of the item to use as the master item:'].toLowerCase()).toContain(es['Master item'].toLowerCase())
  })
})

describe('Polish address', () => {
  it('keeps informal pronouns lowercase within sentences', () => {
    const midSentence = /[\p{L},;:]\s+(?:Twój|Twoja|Twoje|Twoją|Twojej|Twoi|Twoim|Twoich|Twoimi|Twojego|Twojemu|Tobie|Ciebie|Cię|Ci)(?!\p{L})/u
    expect(Object.entries(pl).filter(([, translated]) => midSentence.test(translated))).toEqual([])
  })
})

describe('Finnish item terminology', () => {
  it.each([
    'Merge Items',
    'Items merged.',
    'Could not load the item fields.',
    'Change Item Type',
    'Are you sure you want to change the item type?',
  ] as const)('uses the library item term in “%s”', (key) => {
    expect(fi[key]).toMatch(/nimik/iu)
  })

  it('names the master item consistently in the version instructions', () => {
    expect(fi['Master item']).toBe('Pääversio')
    expect(fi['Choose the version of the item to use as the master item:']).toMatch(/pääversiona/u)
  })

  it('spells the field-selection instruction correctly', () => {
    expect(fi['Select fields to keep from other versions of the item:']).toMatch(/^Valitse /u)
  })
})

describe.each([
  ['sk', sk, /záznam/iu],
  ['sl', sl, /vnos/iu],
  ['ro', ro, /înregistr/iu],
  ['tr', tr, /eser/iu],
] as const)('merge item terminology in %s', (_tag, catalogue, itemTerm) => {
  it.each([
    'Master item',
    'Items merged.',
    'Could not load the item fields.',
  ] as const)('uses the library item term in “%s”', (key) => {
    expect(catalogue.Items).toMatch(itemTerm)
    expect(catalogue[key]).toMatch(itemTerm)
  })
})

it('keeps the Slovenian merge action free of trailing whitespace', () => {
  expect(sl['Merge Items']).toBe(sl['Merge Items'].trim())
})

it('uses the Slovenian library Trash term in the merge warning', () => {
  expect(sl.Trash).toBe('Koš')
  expect(sl['Other versions will be moved to the trash.']).toContain('v koš.')
})

describe('Romanian item terminology', () => {
  it.each([
    'Items moved to trash.',
    'Items filed.',
    'Items restored.',
  ] as const)('keeps the library item term in the confirmation “%s”', (key) => {
    expect(ro[key]).toMatch(/înregistr/iu)
  })

  it('uses the master-item label in the version instruction', () => {
    expect(ro['Choose the version of the item to use as the master item:'].toLowerCase()).toContain(ro['Master item'].toLowerCase())
  })
})

describe('Swedish item terminology', () => {
  it.each([
    'Master item',
    'Items merged.',
    'Could not load the item fields.',
    'Add Related',
    'Remove Related',
    'New Item',
    'New Item Note',
    'First or last item',
    'Previous or next item',
    'Ten items up or down',
    'Show the item’s details',
  ] as const)('keeps the library item term in “%s”', (key) => {
    expect(sv.Items).toBe('Källor')
    expect(sv[key]).toMatch(/käll/iu)
  })
})

describe('Latvian item terminology', () => {
  it.each([
    'Master item',
    'Merge Items',
    'Choose the version of the item to use as the master item:',
    'Select fields to keep from other versions of the item:',
    'Merged items must all be of the same item type.',
    'Items merged.',
    'Could not load the item fields.',
    'New Item',
    'First or last item',
    'Previous or next item',
    'Ten items up or down',
    'Show the item’s details',
  ] as const)('keeps the library item term in “%s”', (key) => {
    expect(lv.Items).toBe('Vienumi')
    expect(lv[key]).toMatch(/vienum/iu)
  })
})

describe('Latvian Trash terminology', () => {
  it.each([
    'Items moved to trash.',
    'Other versions will be moved to the trash.',
  ] as const)('uses the library Trash term in “%s”', (key) => {
    expect(lv.Trash).toBe('Miskaste')
    expect(lv[key]).toMatch(/miskast/iu)
  })
})

describe('Ukrainian item terminology', () => {
  it.each([
    'Master item',
    'Items merged.',
    'Could not load the item fields.',
    'First or last item',
    'Previous or next item',
    'Ten items up or down',
    'Show the item’s details',
  ] as const)('uses the library item term in “%s”', (key) => {
    expect(uk.Items).toBe('Документи')
    expect(uk[key]).toMatch(/документ/iu)
  })

  it('names the master document in the version instruction', () => {
    expect(uk['Choose the version of the item to use as the master item:']).toMatch(/основн.*документ/iu)
  })

  it('keeps other versions plural in the field-selection instruction', () => {
    expect(uk['Select fields to keep from other versions of the item:']).toContain('інших версій документа')
  })
})

describe('Russian item terminology', () => {
  it.each([
    'Merge Items',
    'Choose the version of the item to use as the master item:',
    'Select fields to keep from other versions of the item:',
    'New Item',
    'First or last item',
    'Previous or next item',
    'Ten items up or down',
    'Show the item’s details',
  ] as const)('uses the library item term in “%s”', (key) => {
    expect(ru.Items).toBe('Записи')
    expect(ru[key]).toMatch(/запис/iu)
  })
})

describe('Japanese library terminology', () => {
  it.each([
    'Items moved to trash.',
    'Items filed.',
    'Items restored.',
    'Master item',
    'Items merged.',
    'Could not load the item fields.',
    'Add, change and remove things in your library',
    'Days an item stays in the trash',
    'Deleting an item out of the trash is a write like any other: the library takes a new version and every client learns what went. There is no undo.',
    'Deleting them cannot be undone. Anything uploaded in the last day is left alone, because a file reaches the disk before the item that refers to it.',
    'Everything in it is deleted: items, collections, tags and attachments. Nothing is moved to the trash.',
    'Items',
    'Items added or changed',
    'Items deleted',
    'No items carry the selected tags.',
    'No items match this search and the selected tags.',
    'No items match this search.',
    'Only their own items',
    'The items in it stay in the library.',
    'Who may add and change items',
    'Your page is hidden. Your items stay in My Publications, so it can be opened again.',
    '{count} item added or changed | {count} items added or changed',
    '{count} item deleted | {count} items deleted',
    '{count} items out of the trash',
  ] as const)('uses Zotero’s item term in “%s”', (key) => {
    expect(ja[key]).toContain('項目')
    expect(ja[key]).not.toContain('アイテム')
  })

  it.each([
    'Items moved to trash.',
    'Other versions will be moved to the trash.',
    'Days an item stays in the trash',
    'Deleting an item out of the trash is a write like any other: the library takes a new version and every client learns what went. There is no undo.',
    'In the trash',
    'Zero keeps the trash for good, which is what this server does until you say otherwise. zotero.org uses 30.',
    '{count} items out of the trash',
  ] as const)('uses the sidebar Trash spelling in “%s”', (key) => {
    expect(ja.Trash).toBe('ごみ箱')
    expect(ja[key]).toContain(ja.Trash)
  })
})

it('uses the Ukrainian library Trash term in the merge warning', () => {
  expect(uk.Trash).toBe('Кошик')
  expect(uk['Other versions will be moved to the trash.']).toContain('до Кошика')
})

describe('Turkish merge instructions', () => {
  it.each([
    'Choose the version of the item to use as the master item:',
    'Select fields to keep from other versions of the item:',
  ] as const)('keeps polite plural address in “%s”', (key) => {
    expect(tr[key]).toMatch(/seçiniz:$/u)
  })
})

describe('Afrikaans address', () => {
  it('keeps formal address in editing messages as well as account instructions', () => {
    const informal = /\b(?:jy|jou|joune|julle)\b/iu
    expect(Object.entries(af).filter(([, translated]) => informal.test(translated))).toEqual([])
  })
})

describe.each([
  ['es', es, 'sesión', /navegadores.*se han cerrado/iu],
  ['pt-PT', ptPT, 'sessão', /navegadores.*foram terminados/iu],
] as const)('session termination in %s', (_tag, catalogue, session, closedBrowsers) => {
  it.each([
    'Password changed. Every other browser was signed out.',
    'Password set. Every other signed-in browser was signed out.',
    'Password set. Their other browsers were signed out.',
  ] as const)('describes ended sessions in “%s”', (key) => {
    expect(catalogue[key]).toContain(session)
    expect(catalogue[key]).not.toMatch(closedBrowsers)
  })
})

describe.each([
  ['en-US', en, 'trash'],
  ['en-GB', enGB, 'bin'],
] as const)('English deletion warnings in %s', (_tag, catalogue, trash) => {
  it.each([
    'Everything in it is deleted: items, collections, tags and attachments. Nothing is moved to the trash.',
    'Everything in your library on this server is deleted first, files included. Nothing is moved to the trash.',
    'Everything in {name} is deleted first, files included. Nothing is moved to the trash.',
  ] as const)('directly explains that deleted content bypasses Trash in “%s”', (key) => {
    expect(catalogue[key]).toContain(`Nothing is moved to the ${trash}.`)
  })
})

describe.each([
  ['af', af, /rondom/iu],
  ['da', da, /omkring/iu],
  ['de', de, /herum/iu, undefined, /Nichts wird in den Papierkorb verschoben/u],
  ['es', es, /alrededor/iu, undefined, /Nada se mueve a la Papelera/u],
  ['eu', eu, /inguruan/iu, /zaborr/iu],
  ['fr', fr, /autour/iu],
  ['gl', gl, /ao seu redor/iu, undefined, /Nada se move ao Lixo/u],
  ['is', icelandic, /utan um/iu],
  ['it', italian, /attorno/iu],
  ['ja', ja, /外側|ライブラリーにはごみ箱がありません/u, undefined, /ごみ箱には移動しません/u],
  ['lv', lv, /miskastes tam nav|Bibliotēkai nav miskastes/iu, /miskast/iu, /Nekas netiek pārvietots uz miskasti\./u],
  ['nb', nb, /rundt/iu],
  ['nl', nl, /omheen|om een bibliotheek heen/iu],
  ['nn', nn, /rundt/iu],
  ['pl', pl, /wokół/iu],
  ['pt-BR', ptBR, /em volta/iu],
  ['pt-PT', ptPT, /à volta/iu],
  ['ru', ru, /вокруг/iu, /корзин/iu],
  ['sl', sl, /koša za to ni|ni koša/iu, /koš/iu, /Nič se ne premakne v koš\./u],
  ['sv', sv, /runt/iu],
  ['uk', uk, /Кошика (?:для цього )?немає/u, /кошик/iu, /Нічого не переміщується до Кошика\./u],
  ['zh-CN', zhCN, /外面/u, undefined, /不会移入回收站/u],
  ['zh-TW', zhTW, /外面/u, undefined, /不會移至垃圾筒/u],
] as const)('destructive warnings in %s', (_tag, catalogue, spatialTranslation, trashTerm: string | RegExp = catalogue.Trash.toLowerCase(), bypassesTrash?: RegExp) => {
  it.each([
    'Everything in it is deleted: items, collections, tags and attachments. Nothing is moved to the trash.',
    'Everything in your library on this server is deleted first, files included. Nothing is moved to the trash.',
    'Everything in {name} is deleted first, files included. Nothing is moved to the trash.',
  ] as const)('uses the Trash term without a literal spatial metaphor in “%s”', (key) => {
    // Basque and Russian inflect the UI noun in these sentences.
    expect(catalogue[key].toLowerCase()).toMatch(trashTerm)
    expect(catalogue[key]).not.toMatch(spatialTranslation)
    if (bypassesTrash) expect(catalogue[key]).toMatch(bypassesTrash)
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
