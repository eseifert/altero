// @vitest-environment node
//
// No DOM is involved, and under jsdom `import.meta.url` is rewritten to an
// http URL that cannot be read from disk.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/** The stylesheet itself, read beside this file. */
const TOKENS = readFileSync(fileURLToPath(new URL('./tokens.css', import.meta.url)), 'utf8')

/**
 * The palette, measured.
 *
 * A colour system is only accessible if the pairs it is actually used in clear
 * the thresholds, so this reads the tokens and checks the combinations the
 * interface puts on screen. WCAG 2.2 asks for 4.5:1 for body text (1.4.3) and
 * 3:1 for the parts of a control that identify it — its border, its focus ring
 * (1.4.11). Dividers and decoration are exempt from that second rule, which is
 * exactly the distinction between `outline` and `outline-variant`: the first
 * bounds something you can operate, the second separates things you cannot.
 */

type Scheme = 'light' | 'dark'

function palette(): Record<string, Record<Scheme, string>> {
  const colours: Record<string, Record<Scheme, string>> = {}

  const pairs = TOKENS.matchAll(
    /--md-sys-color-([\w-]+):\s*light-dark\((#[0-9a-fA-F]{6}),\s*(#[0-9a-fA-F]{6})\)/g,
  )
  for (const [, name, light, dark] of pairs) {
    colours[name] = { light, dark }
  }

  for (const [, name, flat] of TOKENS.matchAll(/--md-sys-color-([\w-]+):\s*(#[0-9a-fA-F]{6});/g)) {
    colours[name] = { light: flat, dark: flat }
  }

  return colours
}

function luminance(colour: string): number {
  const channels = [1, 3, 5].map((index) => parseInt(colour.slice(index, index + 2), 16) / 255)
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(foreground: string, background: string): number {
  const a = luminance(foreground)
  const b = luminance(background)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/** Text pairs, which need 4.5:1. */
const TEXT: Array<[string, string, string]> = [
  ['on-background', 'background', 'body text'],
  ['on-surface', 'surface', 'text on a surface'],
  ['on-surface-variant', 'surface', 'secondary text'],
  ['on-surface-variant', 'surface-container', 'secondary text on a card'],
  ['on-surface-variant', 'surface-container-high', 'secondary text, high container'],
  ['on-surface', 'surface-container', 'text on a card'],
  ['on-surface', 'surface-container-high', 'text on a high container'],
  ['primary', 'surface', 'accent text'],
  ['primary', 'surface-container', 'accent text on a card'],
  ['on-primary', 'primary', 'filled button label'],
  ['on-secondary-container', 'secondary-container', 'selected row label'],
  ['on-primary-container', 'primary-container', 'text in a primary container'],
  ['on-tertiary-container', 'tertiary-container', 'text in a tertiary container'],
  ['error', 'surface', 'error text'],
  ['on-error', 'error', 'text on error'],
  ['on-error-container', 'error-container', 'text in an error container'],
  ['inverse-on-surface', 'inverse-surface', 'text on the inverse surface'],
]

/** Control borders and focus rings, which need 3:1. */
const CONTROLS: Array<[string, string, string]> = [
  ['outline', 'surface', 'control border'],
  ['outline', 'surface-container', 'control border on a card'],
  ['outline', 'surface-container-high', 'control border, high container'],
  ['primary', 'surface', 'focus ring'],
  ['primary', 'surface-container', 'focus ring on a card'],
  ['primary', 'surface-container-high', 'focus ring in a toolbar or a dialog'],
  ['error', 'surface', 'invalid field border'],
  ['error', 'surface-container-high', 'a danger glyph in a toolbar'],
  /* The bar down the leading edge of the current row, which is what says
     "this one" to a reader for whom the fill alone does not (1.4.1). */
  ['primary', 'secondary-container', 'the bar on the current row'],
]

/**
 * The hover wash, resolved.
 *
 * `--md-sys-state-hover-surface` is a `color-mix` against `transparent`, so
 * what lands on screen depends on what is under it. This reads the percentage
 * out of the stylesheet and composites it, which is the only way to measure a
 * state layer at all.
 */
function washed(over: string, scheme: Scheme): string {
  const found = TOKENS.match(
    /--md-sys-state-hover-surface:\s*color-mix\(\s*in srgb,\s*var\(--md-sys-color-([\w-]+)\)\s*([\d.]+)%/,
  )
  if (!found) throw new Error('No hover wash in tokens.css')

  const [, source, percent] = found
  const alpha = Number(percent) / 100
  const channels = (colour: string) =>
    [1, 3, 5].map((index) => parseInt(colour.slice(index, index + 2), 16))

  const top = channels(colours[source][scheme])
  const bottom = channels(colours[over][scheme])
  return (
    '#' +
    top
      .map((value, index) => Math.round(value * alpha + bottom[index] * (1 - alpha)))
      .map((value) => value.toString(16).padStart(2, '0'))
      .join('')
  )
}

/** The surfaces a hoverable row or control actually sits on. */
const HOVERED = [
  ['surface', 'a row of the item list, a sidebar row'],
  ['surface-container', 'a row or a control on a card'],
  ['surface-container-high', 'a glyph in a toolbar, a control in a dialog'],
]

const colours = palette()
const schemes: Scheme[] = ['light', 'dark']

describe('the colour system', () => {
  it.each(TEXT)('reads %s on %s: %s', (foreground, background, description) => {
    for (const scheme of schemes) {
      const ratio = contrast(colours[foreground][scheme], colours[background][scheme])
      expect(ratio, `${description} in ${scheme}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it.each(CONTROLS)('shows %s on %s: %s', (foreground, background, description) => {
    for (const scheme of schemes) {
      const ratio = contrast(colours[foreground][scheme], colours[background][scheme])
      expect(ratio, `${description} in ${scheme}`).toBeGreaterThanOrEqual(3)
    }
  })

  /*
   * Hover has no WCAG threshold: it is a pointer affordance rather than
   * information, and nothing is lost by a reader who never sees it. What it
   * cannot be is invisible, which is what it was -- the item list washed its
   * rows with `surface-container-low` over a white page, 1.03:1, a difference a
   * screen at an angle does not show at all. 1.2:1 is roughly where a large
   * block of flat colour separates from its background; the floor sits above
   * it so the wash clears that on every surface rather than on the kindest one.
   */
  it.each(HOVERED)('washes %s: %s', (surface, description) => {
    for (const scheme of schemes) {
      const ratio = contrast(washed(surface, scheme), colours[surface][scheme])
      expect(ratio, `hover on ${description} in ${scheme}`).toBeGreaterThanOrEqual(1.25)
    }
  })

  it('marks a chosen row more strongly than the pointer does', () => {
    /* Hover and selection are both washes of the same rows, so their order is
       what says which one means "chosen". A hover that outweighed the selection
       would make the row under the pointer look picked out and the picked-out
       rows look passed over. */
    for (const scheme of schemes) {
      const hover = contrast(washed('surface', scheme), colours.surface[scheme])
      const selected = contrast(colours['secondary-container'][scheme], colours.surface[scheme])
      expect(selected, `selection against hover in ${scheme}`).toBeGreaterThan(hover)
    }
  })

  it('declares every colour for both schemes', () => {
    /* A token defined for one scheme only is invisible in the other, and the
       failure is easy to miss on the theme you do not use. */
    const declared = TOKENS.match(/--md-sys-color-[\w-]+:/g) ?? []

    expect(declared).toHaveLength(Object.keys(colours).length)
  })
})
