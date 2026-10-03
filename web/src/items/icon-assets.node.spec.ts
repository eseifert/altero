// @vitest-environment node
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, it } from 'vitest'

const source = fileURLToPath(new URL('../', import.meta.url))

it('keeps icon drawings in editable SVG files rather than application code', () => {
  const files = readdirSync(source, { recursive: true }) as string[]
  const offenders = files
    .filter((name) => /\.(vue|ts|css)$/.test(name) && !name.endsWith('.spec.ts'))
    .filter((name) => {
      const content = readFileSync(`${source}${name}`, 'utf8')
      return /<(path|circle|rect|polygon|polyline|ellipse|line)\b|['"`]M\d|data:image\/svg/.test(content)
    })

  expect(offenders).toEqual([])
})
