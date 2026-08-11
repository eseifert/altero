// @vitest-environment node
//
// Reads the source tree, so it wants files rather than a DOM.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/**
 * The design system, enforced.
 *
 * `docs/design.md` says what a bounded area looks like, and `surfaces.css` is
 * the one place it is written as CSS. This is what keeps that true: the
 * interface grew three different cards -- an outlined one in settings, a
 * filled one in the administration screens, and a third step for everything
 * else -- and every one of them looked deliberate in the file it was in.
 *
 * Two rules, both about components rather than about the shared stylesheets:
 *
 * - a component may not paint a surface step of its own, and
 * - a component may not draw a card, which is a medium corner with a border.
 *
 * A legitimate exception is a line in the list below, which somebody has to
 * mean rather than a CSS block somebody copied.
 */

const SOURCE = fileURLToPath(new URL('../', import.meta.url))

/**
 * Where a surface may be painted.
 *
 * The four shared stylesheets are the vocabulary itself. The three components
 * are the exceptions and each is a different one: the application bar is
 * chrome rather than a card, the theme menu is a floating menu, and the
 * publications dialog fills a step above the dialog it sits in.
 */
const MAY_PAINT = [
  'styles/surfaces.css',
  'styles/dialog.css',
  'styles/base.css',
  'styles/auth-form.css',
  'App.vue',
  'components/ThemeMenu.vue',
  'components/PublicationsDialog.vue',
]

/** Every file that can carry CSS, as a path relative to `src/`. */
function stylesheets(): string[] {
  const found: string[] = []

  const walk = (directory: string, prefix: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = `${directory}${entry.name}`
      if (entry.isDirectory()) {
        walk(`${path}/`, `${prefix}${entry.name}/`)
      } else if (/\.(vue|css)$/.test(entry.name)) {
        found.push(`${prefix}${entry.name}`)
      }
    }
  }

  walk(SOURCE, '')
  return found
}

function read(name: string): string {
  return readFileSync(`${SOURCE}${name}`, 'utf8')
}

describe('the surfaces a component paints', () => {
  it('finds the tree to check', () => {
    expect(stylesheets().length).toBeGreaterThan(20)
  })

  it('is left to the shared stylesheets', () => {
    /* `surface-container*` is depth, and depth belongs to the system. The
       other containers are meaning -- `secondary-container` marks a choice,
       `error-container` marks a loss -- and a component says those for
       itself. */
    const offenders = stylesheets()
      .filter((name) => !MAY_PAINT.includes(name))
      .filter((name) => /background:\s*var\(--md-sys-color-surface-container/.test(read(name)))

    expect(offenders).toEqual([])
  })

  it('never uses the steps below the page', () => {
    /* `surface-container-low` and `-lowest` exist because Material defines
       them. Over a white page they are all but invisible -- 1.03:1 -- so
       whatever they were meant to separate was not separated. */
    const offenders = stylesheets().filter((name) =>
      /var\(--md-sys-color-surface-container-low/.test(read(name)),
    )

    expect(offenders).toEqual([])
  })

  it('does not draw a card of its own', () => {
    /* The outlined card this system replaced: an area bounded in the divider
       colour. `outline` is a different matter -- that is a control saying
       where it can be operated, and the tag pills use it deliberately. What
       is checked is therefore the divider, which divides and never bounds. */
    const offenders = stylesheets()
      .filter((name) => !MAY_PAINT.includes(name))
      .filter((name) =>
        /border:\s*1px solid var\(--md-sys-color-outline-variant\);\s*\n\s*border-radius:\s*var\(--md-sys-shape-corner-(medium|large)\)/.test(
          read(name),
        ),
      )

    expect(offenders).toEqual([])
  })
})
