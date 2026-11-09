/** Standalone catalog validation. Never imported by the application's tests. */
import { readdir } from 'node:fs/promises'

import { createParser } from '@intlify/message-compiler'

type Catalog = Record<string, string>
type Message = { branches: string[][]; errors: string[] }

export function checkCatalogs(catalogs: Record<string, unknown>) {
  const errors: string[] = []
  const warnings: string[] = []
  const parsed = new Map<string, Message>()
  const valid = new Map<string, Catalog>()

  // The same English messages occur in many catalogs. Parse each distinct
  // message once, including plural branches and literal escapes.
  function message(text: string): Message {
    const cached = parsed.get(text)
    if (cached) return cached
    const result: Message = { branches: [], errors: [] }
    const ast = createParser({ onError: (error) => result.errors.push(error.message) }).parse(text)
    // NodeTypes is a compile-time enum; native Node TypeScript strips types.
    const branches = ast.body.type === 1 ? ast.body.cases : [ast.body]
    result.branches = branches.map((branch) => [...new Set(branch.items.flatMap((item) => {
      if (item.type === 4) return [`named:${item.key}`]
      if (item.type === 5) return [`list:${item.index}`]
      return []
    }))].sort())
    parsed.set(text, result)
    return result
  }

  for (const [tag, catalog] of Object.entries(catalogs)) {
    if (!catalog || typeof catalog !== 'object' || Array.isArray(catalog)) {
      errors.push(`${tag}: default export must be a message object`)
      continue
    }
    const entries = Object.entries(catalog)
    if (entries.some(([, value]) => typeof value !== 'string')) {
      errors.push(`${tag}: every message must be a string`)
      continue
    }
    valid.set(tag, catalog as Catalog)
    for (const [key, value] of entries) {
      for (const error of message(value).errors) errors.push(`${tag}: ${key}: ${error}`)
    }
  }

  const source = valid.get('en-US')
  if (!source) errors.push('en-US: canonical catalog is required')
  else for (const [tag, catalog] of valid) {
    if (tag === 'en-US') continue
    const missing = Object.keys(source).filter((key) => !Object.hasOwn(catalog, key))
    const obsolete = Object.keys(catalog).filter((key) => !Object.hasOwn(source, key))
    if (missing.length) warnings.push(`${tag}: ${missing.length} missing keys: ${missing.join(', ')}`)
    if (obsolete.length) warnings.push(`${tag}: ${obsolete.length} obsolete keys: ${obsolete.join(', ')}`)
    for (const [key, value] of Object.entries(catalog)) {
      if (!Object.hasOwn(source, key)) continue
      const original = message(source[key])
      const translated = message(value)
      if (original.errors.length || translated.errors.length) continue
      if (original.branches.length === 1 && translated.branches.length > 1) {
        errors.push(`${tag}: ${key}: unexpected plural message`)
      }
      for (const [index, branch] of translated.branches.entries()) {
        const wanted = original.branches[Math.min(index, original.branches.length - 1)]
        if (JSON.stringify(branch) !== JSON.stringify(wanted)) {
          errors.push(`${tag}: ${key}: incompatible placeholders in branch ${index + 1}`)
        }
      }
    }
  }
  return { errors, warnings }
}

if (import.meta.main) {
  const directory = new URL('../src/locales/', import.meta.url)
  const catalogs: Record<string, unknown> = {}
  const loadErrors: string[] = []
  for (const name of (await readdir(directory)).sort()) {
    if (!name.endsWith('.ts') || name.endsWith('.spec.ts')) continue
    try {
      catalogs[name.slice(0, -3)] = (await import(new URL(name, directory).href)).default
    } catch (error) {
      loadErrors.push(`${name}: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
  const { errors, warnings } = checkCatalogs(catalogs)
  for (const warning of warnings) console.warn(`Warning: ${warning}`)
  for (const error of [...loadErrors, ...errors]) console.error(`Error: ${error}`)
  console.log(`Checked ${Object.keys(catalogs).length} catalogs; ${loadErrors.length + errors.length} errors, ${warnings.length} warnings.`)
  process.exitCode = loadErrors.length || errors.length ? 1 : 0
}
