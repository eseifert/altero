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
  ['on-surface-variant', 'surface-container-low', 'secondary text, low container'],
  ['on-surface-variant', 'surface-container-high', 'secondary text, high container'],
  ['on-surface', 'surface-container-low', 'text on a low container'],
  ['on-surface', 'surface-container', 'text on a container'],
  ['on-surface', 'surface-container-high', 'text on a high container'],
  ['primary', 'surface', 'accent text'],
  ['primary', 'surface-container-low', 'accent text, low container'],
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
  ['outline', 'surface-container-low', 'control border, low container'],
  ['outline', 'surface-container-high', 'control border, high container'],
  ['primary', 'surface', 'focus ring'],
  ['primary', 'surface-container-low', 'focus ring, low container'],
  ['primary', 'surface-container-high', 'focus ring, high container'],
  ['error', 'surface', 'invalid field border'],
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

  it('declares every colour for both schemes', () => {
    /* A token defined for one scheme only is invisible in the other, and the
       failure is easy to miss on the theme you do not use. */
    const declared = TOKENS.match(/--md-sys-color-[\w-]+:/g) ?? []

    expect(declared).toHaveLength(Object.keys(colours).length)
  })
})
