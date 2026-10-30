// @vitest-environment node
//
// Reads the source tree, so it wants files rather than a DOM.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { list, parse } from 'postcss'
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
 * Stylesheets, component style blocks, asymmetric margin/padding shorthands
 * and inline style bindings must all follow the document's direction.
 */

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

/** Four-sided shorthands hide a physical start/end when the sides differ. */
function asymmetric(text: string): string[] {
  const found: string[] = []
  parse(text).walkDecls(/^(margin|padding)$/, (decl) => {
    const sides = list.space(decl.value)
    if (sides.length === 4 && sides[1] !== sides[3]) found.push(decl.toString())
  })
  return found
}

function bindings(text: string): string[] {
  return [...text.matchAll(/:style="([^"]*)"/g)].flatMap((binding) =>
    binding[1].match(/\b(?:margin|padding|border)(?:Left|Right|-(?:left|right))\b|\b(?:left|right)'?\s*:|\btextAlign\s*:\s*'(?:left|right)'/g) ?? [],
  )
}

describe('sides in the stylesheets', () => {
  it('finds the tree to check', () => {
    expect(stylesheets().length).toBeGreaterThan(20)
  })

  it('are said as start and end throughout the interface', () => {
    const offenders = stylesheets().flatMap((name) => [
      ...physical(name),
      ...asymmetric(css(name)),
      ...bindings(readFileSync(`${SOURCE}${name}`, 'utf8')),
    ].map((found) => `${name}: ${found}`))

    expect(offenders, 'use logical properties, including in shorthands and style bindings').toEqual([])
  })

  it('detects asymmetric shorthands with functions in their values', () => {
    expect(asymmetric('a { padding: 0 var(--gap) 1rem calc(var(--gap) + 18px) }')).toEqual([
      'padding: 0 var(--gap) 1rem calc(var(--gap) + 18px)',
    ])
    expect(asymmetric('a { margin: 0.75rem 0 0 0.75rem }')).toHaveLength(1)
    expect(asymmetric('a { padding: 1px 2px 3px 2px; margin: 1px 2px 3px }')).toEqual([])
  })

  it('detects physical properties in inline styles', () => {
    expect(bindings(`<div :style="{ paddingLeft: '2rem', right: '0' }" />`)).toEqual([
      'paddingLeft', 'right:',
    ])
    expect(bindings(`<div :style="{ paddingInlineStart: '2rem' }" />`)).toEqual([])
    expect(bindings(`<div :style="{
      'margin-left': '2rem', textAlign: 'right'
    }" />`)).toEqual(['margin-left', "textAlign: 'right'"])
  })
})
