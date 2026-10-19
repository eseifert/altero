// @vitest-environment node
//
// Runs a real build, since what can go wrong is when the plugin's hook runs
// relative to Vite's own, and only a build orders them.
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { brotliDecompressSync, gunzipSync } from 'node:zlib'

import { build, type Rolldown } from 'vite'
import { afterAll, describe, expect, it } from 'vitest'

import { precompress } from '../vite.config'

const ROOT = mkdtempSync(join(tmpdir(), 'altero-precompress-'))
afterAll(() => rmSync(ROOT, { recursive: true, force: true }))

/** Builds an entry with a dynamic import, the case Vite rewrites after rendering. */
async function bundle(): Promise<Rolldown.OutputBundle> {
  // Large enough to pass the plugin's 1 kB floor.
  const filler = `console.log(${JSON.stringify('x'.repeat(2048))})\n`
  writeFileSync(join(ROOT, 'lazy.js'), `${filler}export default 'lazy'\n`)
  writeFileSync(
    join(ROOT, 'main.js'),
    `${filler}globalThis.load = () => import('./lazy.js').then((m) => m.default)\n`,
  )
  const result = await build({
    root: ROOT,
    configFile: false,
    logLevel: 'silent',
    plugins: [precompress()],
    build: { write: false, rollupOptions: { input: join(ROOT, 'main.js') } },
  })
  const outputs = Array.isArray(result) ? result : [result as Rolldown.RolldownOutput]
  return Object.fromEntries(outputs.flatMap((o) => o.output).map((file) => [file.fileName, file]))
}

describe('precompress', () => {
  it('compresses each chunk as it is finally written, not as it was first rendered', async () => {
    const files = await bundle()
    const chunks = Object.values(files).filter((file) => file.type === 'chunk')
    expect(chunks.length).toBeGreaterThan(1)

    for (const chunk of chunks) {
      const plain = Buffer.from(chunk.code)
      const br = files[`${chunk.fileName}.br`]
      const gz = files[`${chunk.fileName}.gz`]
      expect(br?.type, chunk.fileName).toBe('asset')
      expect(gz?.type, chunk.fileName).toBe('asset')
      if (br?.type !== 'asset' || gz?.type !== 'asset') continue
      expect(brotliDecompressSync(br.source).equals(plain), `${chunk.fileName}.br`).toBe(true)
      expect(gunzipSync(gz.source).equals(plain), `${chunk.fileName}.gz`).toBe(true)
    }
  })
})
