// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const ICONS = new URL('../assets/icons/', import.meta.url)
const directional = [
  'controls/align', 'controls/chevron-right', 'controls/open', 'controls/undo', 'controls/redo',
  'sidebar/move', 'sidebar/restore',
]

describe('directional icons', () => {
  it.each(directional)('marks %s for mirroring wherever it is rendered', (name) => {
    expect(readFileSync(new URL(`${name}.svg`, ICONS), 'utf8')).toMatch(/<svg\s[^>]*data-mirror-rtl=/)
  })

  it('preserves tree rotations while mirroring the rendered SVG', () => {
    const component = readFileSync(new URL('../components/SvgIcon.vue', import.meta.url), 'utf8')
    expect(component).toMatch(/svg\[data-mirror-rtl\]:dir\(rtl\)\s*\{\s*scale:\s*-1 1;/)
  })

  it.each(['controls/bold', 'controls/chevron-down', 'sidebar/export', 'items/book'])(
    'keeps %s in its original orientation', (name) => {
      expect(readFileSync(new URL(`${name}.svg`, ICONS), 'utf8')).not.toContain('data-mirror-rtl')
    },
  )
})
