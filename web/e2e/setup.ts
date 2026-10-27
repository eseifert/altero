/**
 * Start a real server on a throwaway database and seed it.
 *
 * The account and its key come from the command line, as on a real instance;
 * the library comes in through the v3 API, as a desktop client would sync it.
 * What was made is written to `e2e/.state.json` for the tests to read.
 */
import { type ChildProcess, execFileSync, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { PASSWORD, STATE_FILE, type State, USERNAME } from './state'

const ROOT = resolve(import.meta.dirname, '..', '..')
const PORT = process.env.ALTERO_E2E_PORT ?? '8766'
const BASE = `http://127.0.0.1:${PORT}`

/** The installed environment when there is one, as the rest of the checks use. */
function command(name: string): [string, string[]] {
  const local = join(ROOT, '.venv', 'bin', name)
  return existsSync(local) ? [local, []] : ['uv', ['run', name]]
}

function run(name: string, args: string[], env: NodeJS.ProcessEnv, input?: string): string {
  const [program, prefix] = command(name)
  return execFileSync(program, [...prefix, ...args], { cwd: ROOT, env, input, encoding: 'utf8' })
}

async function waitFor(url: string): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      if ((await fetch(url)).ok) return
    } catch {
      // Not listening yet.
    }
    await new Promise((done) => setTimeout(done, 200))
  }
  throw new Error(`The server did not answer at ${url}`)
}

/** The v3 API, as the seeded account. */
function api(key: string) {
  return async (path: string, init: RequestInit = {}): Promise<Response> => {
    const response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Zotero-API-Key': key, ...(init.headers ?? {}) },
    })
    if (!response.ok) throw new Error(`${init.method ?? 'GET'} ${path}: ${response.status}`)
    return response
  }
}

async function create(call: ReturnType<typeof api>, objects: unknown[]): Promise<string[]> {
  const response = await call('/users/1/items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(objects),
  })
  const body = (await response.json()) as { successful: Record<string, { key: string }> }
  return objects.map((_, index) => body.successful[String(index)]!.key)
}

/** The desktop client's three-step upload. */
async function attach(call: ReturnType<typeof api>, key: string, content: string, type: string) {
  const bytes = Buffer.from(content)
  const authorized = (await (
    await call(`/users/1/items/${key}/file`, {
      method: 'POST',
      headers: { 'If-None-Match': '*', 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        md5: createHash('md5').update(bytes).digest('hex'),
        filename: 'page.html',
        filesize: String(bytes.length),
        mtime: '1700000000000',
        contentType: type,
      }),
    })
  ).json()) as { url: string; uploadKey: string }
  await fetch(authorized.url, { method: 'POST', body: bytes })
  await call(`/users/1/items/${key}/file`, {
    method: 'POST',
    headers: { 'If-None-Match': '*', 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ upload: authorized.uploadKey }),
  })
}

export default async function setup(): Promise<() => void> {
  if (!existsSync(join(ROOT, 'src', 'altero', 'web', 'static', 'index.html'))) {
    throw new Error('Build the interface first: npm run build')
  }

  const directory = mkdtempSync(join(tmpdir(), 'altero-e2e-'))
  const env = {
    ...process.env,
    ALTERO_DATABASE_URL: `sqlite+aiosqlite:///${join(directory, 'altero.sqlite')}`,
    ALTERO_STORAGE_PATH: join(directory, 'storage'),
    ALTERO_PORT: PORT,
  }

  run('alembic', ['upgrade', 'head'], env)
  run('altero', ['user', 'add', USERNAME, '--display-name', 'Ada Lovelace'], env)
  run('altero', ['user', 'password', USERNAME], env, `${PASSWORD}\n${PASSWORD}\n`)
  run('altero', ['user', 'admin', USERNAME], env)
  const key = /Key for \S+: (\S+)/.exec(run('altero', ['key', 'add', USERNAME], env))?.[1]
  if (!key) throw new Error('No API key was printed')

  const [program, prefix] = command('altero')
  const server: ChildProcess = spawn(program, [...prefix, 'serve'], { cwd: ROOT, env, stdio: 'ignore' })
  await waitFor(`${BASE}/health`)

  const call = api(key)
  const [book] = await create(call, [
    {
      itemType: 'book',
      title: 'Notes on the Analytical Engine',
      creators: [{ creatorType: 'author', firstName: 'Ada', lastName: 'Lovelace' }],
      date: '1843',
      tags: [{ tag: 'computing' }],
      inPublications: true,
    },
  ])
  const [note, page] = await create(call, [
    {
      itemType: 'note',
      parentItem: book,
      inPublications: true,
      // Whatever a client synced, including what it should not have.
      note: '<p>The engine weaves algebraic patterns.</p><img src="x" onerror="window.__ran=1">',
    },
    { itemType: 'attachment', linkMode: 'imported_file', title: 'A page', parentItem: book },
  ])
  await attach(call, page!, '<!doctype html><script>document.title = "ran"</script>', 'text/html')
  // Edited by the creator tests, which no other test reads.
  await create(call, [
    {
      itemType: 'book',
      title: 'Sketch of the Analytical Engine',
      creators: [
        { creatorType: 'author', firstName: 'Luigi', lastName: 'Menabrea' },
        { creatorType: 'translator', firstName: 'Ada', lastName: 'Lovelace' },
      ],
    },
  ])

  // Related and unrelated again by the related-items test, both projects.
  await create(call, [
    { itemType: 'book', title: 'On the Economy of Machinery and Manufactures' },
    { itemType: 'letter', title: 'Letter to Charles Babbage' },
  ])

  const state: State = { baseURL: BASE, key, book: book!, note: note!, page: page! }
  writeFileSync(STATE_FILE, JSON.stringify(state))

  return () => {
    server.kill()
    rmSync(directory, { recursive: true, force: true })
    rmSync(STATE_FILE, { force: true })
  }
}
