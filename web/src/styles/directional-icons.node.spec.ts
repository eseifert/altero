// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'
import { compileStyle, parse } from '@vue/compiler-sfc'

const ICONS = new URL('../assets/icons/', import.meta.url)
const directional = [
  'controls/align', 'controls/chevron-right', 'controls/open', 'controls/undo', 'controls/redo',
  'sidebar/move', 'sidebar/restore',
]

describe('directional icons', () => {
  it.each(directional)('marks %s for mirroring wherever it is rendered', (name) => {
    expect(readFileSync(new URL(`${name}.svg`, ICONS), 'utf8')).toMatch(/<svg\s[^>]*data-mirror-rtl=/)
  })

  it('preserves tree rotations while mirroring with CSS supported by the browser targets', () => {
    const component = readFileSync(new URL('../components/SvgIcon.vue', import.meta.url), 'utf8')
    const splitter = readFileSync(new URL('../components/PaneSplitter.vue', import.meta.url), 'utf8')
    const css = component.split('<style scoped>')[1]!.replace(/\/\*[\s\S]*?\*\//g, '')
    expect(css).not.toMatch(/:dir\(|(?:^|\n)\s*scale\s*:/)
    expect(splitter).not.toContain(':dir(')
    for (const [source, target] of [[component, 'svg[data-mirror-rtl]'], [splitter, '.splitter']]) {
      const style = parse(source!).descriptor.styles[0]!
      const compiled = compileStyle({ source: style.content, filename: 'icon.vue', id: 'data-v-test', scoped: true })
      expect(compiled.errors).toEqual([])
      expect(compiled.code).toContain(`[dir='rtl'] ${target}[data-v-test]`)
    }
    expect(component).toContain('scaleX(var(--icon-scale, 1)) rotate(var(--icon-angle, 0deg))')
    expect(component).toContain('--icon-scale: -1')
    for (const path of ['../components/CollectionTree.vue', '../views/LibraryView.vue']) {
      expect(readFileSync(new URL(path, import.meta.url), 'utf8')).toContain('--icon-angle: 90deg')
    }
  })

  it.each(['controls/bold', 'controls/chevron-down', 'sidebar/export', 'items/book'])(
    'keeps %s in its original orientation', (name) => {
      expect(readFileSync(new URL(`${name}.svg`, ICONS), 'utf8')).not.toContain('data-mirror-rtl')
    },
  )
})
