// @vitest-environment node
//
// Reads the source tree, so it wants files rather than a DOM.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/**
 * Sides said as start and end, not as left and right.
 *
 * In Arabic, Persian or Hebrew the page runs the other way, and a
 * `margin-left` that set a label off from its icon sets it off from nothing.
 * `margin-inline-start` follows the direction the text runs, which is the
 * difference between an interface that can be mirrored by setting `dir` and
 * one that has to be found and fixed a rule at a time.
 *
 * New CSS says it logically. The files below said it physically before this
 * check existed; each number is how many such declarations the file has, and
 * goes down as they are converted until the list is empty. A file that gains
 * one fails, and so does a file that loses one without its number following,
 * so the list never claims more than is there.
 *
 * Only declarations in stylesheets and `<style>` blocks are read. Shorthands
 * with four sides (`margin: 0 1rem 0 0`) and style bindings in templates are
 * not, and need the same care by hand.
 */
const NOT_YET_LOGICAL: Record<string, number> = {
  'App.vue': 1,
  'components/CollectionDialog.vue': 1,
  'components/CollectionTree.vue': 2,
  'components/ItemDetail.vue': 1,
  'components/PublicationsDialog.vue': 1,
  'components/ThemeMenu.vue': 2,
  'styles/base.css': 1,
  'styles/dialog.css': 2,
  'styles/surfaces.css': 1,
  'views/AuthorizeView.vue': 2,
  'views/LibraryView.vue': 12,
  'views/LinkClientView.vue': 1,
  'views/admin/AccountsSection.vue': 1,
  'views/admin/StorageSection.vue': 2,
  'views/settings/KeysSection.vue': 1,
  'views/settings/MigrateSection.vue': 1,
}

/** A declaration that names a physical side, with what to write instead. */
const PHYSICAL =
  /^\s*(?:(?:margin|padding|border)-(?:left|right)\b|(?:left|right)\s*:|text-align\s*:\s*(?:left|right)\b|float\s*:\s*(?:left|right)\b|clear\s*:\s*(?:left|right)\b|border-(?:top|bottom)-(?:left|right)-radius\b)/gm

const SOURCE = fileURLToPath(new URL('../', import.meta.url))

/** Every file that can carry CSS, as a path relative to `src/`. */
function stylesheets(): string[] {
  const found: string[] = []
  const walk = (directory: string, prefix: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        walk(`${directory}${entry.name}/`, `${prefix}${entry.name}/`)
      } else if (/\.(vue|css)$/.test(entry.name)) {
        found.push(`${prefix}${entry.name}`)
      }
    }
  }
  walk(SOURCE, '')
  return found
}

/** The CSS in a file: all of a stylesheet, only the `<style>` blocks of a component. */
function css(name: string): string {
  const text = readFileSync(`${SOURCE}${name}`, 'utf8')
  if (name.endsWith('.css')) return text
  return [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((block) => block[1]).join('\n')
}

function physical(name: string): string[] {
  return (css(name).match(PHYSICAL) ?? []).map((found) => found.trim())
}

describe('sides in the stylesheets', () => {
  it('finds the tree to check', () => {
    expect(stylesheets().length).toBeGreaterThan(20)
  })

  it('are said as start and end in new CSS', () => {
    const offenders = stylesheets()
      .filter((name) => !(name in NOT_YET_LOGICAL))
      .flatMap((name) => physical(name).map((found) => `${name}: ${found}`))

    expect(offenders, 'use margin-inline-start, inset-inline-end, text-align: start…').toEqual([])
  })

  it('are not said physically more often than the list allows', () => {
    const grown = Object.entries(NOT_YET_LOGICAL)
      .filter(([name, allowed]) => physical(name).length > allowed)
      .map(([name, allowed]) => `${name}: ${physical(name).length} > ${allowed}`)

    expect(grown).toEqual([])
  })

  it('keep the list in step as they are converted', () => {
    const stale = Object.entries(NOT_YET_LOGICAL)
      .filter(([name, allowed]) => physical(name).length < allowed)
      .map(([name, allowed]) => `${name}: lower ${allowed} to ${physical(name).length}`)

    expect(stale).toEqual([])
  })
})
