/** Disposable real SMTP and altero processes; never forwards mail. */
import { execFileSync, spawn } from 'node:child_process'
import { appendFileSync, mkdirSync, mkdtempSync, openSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { get } from 'node:http'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

export const ROOT = resolve(import.meta.dirname, '..')
export const STATE = join(ROOT, 'registration-results/state.json')
export const BASE = 'http://127.0.0.1:8767'
export const PASSWORD = 'a private test administrator passphrase'
export interface State { directory: string; smtpPort: number; pid: number }
export const state = (): State => JSON.parse(readFileSync(STATE, 'utf8'))
const repository = resolve(ROOT, '..')

export function environment(saved: State) {
  const inherited = Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith('ALTERO_')))
  return { ...inherited, ALTERO_CONFIG: join(saved.directory, 'no-config.py'),
    ALTERO_DATABASE_URL: `sqlite+aiosqlite:///${saved.directory}/db.sqlite`,
    ALTERO_STORAGE_PATH: join(saved.directory, 'storage'),
    ALTERO_HOST: '127.0.0.1', ALTERO_PORT: '8767', ALTERO_PUBLIC_URL: BASE,
    ALTERO_SMTP_URL: `smtp://127.0.0.1:${saved.smtpPort}`,
    ALTERO_REGISTRATION_APPROVAL: 'true', ALTERO_OPEN_REGISTRATION: 'true',
    ALTERO_REGISTRATION_IP_LIMIT: '100',
  }
}
export async function start(saved: State): Promise<void> {
  const output = openSync(join(saved.directory, 'server.log'), 'a')
  const server = spawn(join(repository, '.venv/bin/altero'), ['serve'], {
    cwd: repository, env: environment(saved), stdio: ['ignore', output, output],
  })
  saved.pid = server.pid!
  writeFileSync(STATE, JSON.stringify(saved))
  const deadline = Date.now() + 45000
  while (Date.now() < deadline) {
    const healthy = await new Promise<boolean>((done) => {
      const check = get(BASE + '/health', (response) => { response.resume(); done(response.statusCode === 200) })
      check.on('error', () => done(false))
      check.setTimeout(1000, () => { check.destroy(); done(false) })
    })
    if (healthy) return
    if (server.exitCode !== null) throw new Error(`Registration server failed: ${saved.directory}`)
    await new Promise((done) => setTimeout(done, 100))
  }
  throw new Error(`Registration server timed out: ${saved.directory}`)
}
export async function restart(): Promise<void> {
  const saved = state()
  process.kill(saved.pid, 'SIGTERM')
  for (let i = 0; i < 100; i++) {
    try { process.kill(saved.pid, 0) } catch { break }
    await new Promise((done) => setTimeout(done, 100))
  }
  await start(saved)
}
export default async function setup() {
  const directory = mkdtempSync(join(tmpdir(), 'altero-registration-browser-'))
  const mailbox = join(directory, 'mail.jsonl')
  writeFileSync(mailbox, '', { mode: 0o600 })
  const refused = new Set<string>()
  const smtp = createServer((socket) => {
    socket.write('220 localhost test SMTP\r\n')
    let buffer = '', data: string[] | null = null
    socket.on('data', (chunk) => {
      buffer += chunk.toString()
      while (buffer.includes('\r\n')) {
        const end = buffer.indexOf('\r\n'), line = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        if (data !== null) {
          if (line !== '.') { data.push(line.replace(/^\.\./, '.')); continue }
          // The fixture mails are ASCII text with quoted-printable wrapping.
          const text = data.join('\n').replace(/=\n/g, '').replace(/=([A-F0-9]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
          appendFileSync(mailbox, JSON.stringify(text) + '\n')
          data = null; socket.write('250 queued\r\n')
        } else if (/^RCPT TO:\s*<fail-/i.test(line) && !refused.has(line.toLowerCase())) {
          refused.add(line.toLowerCase())
          socket.write('451 temporary fixture failure\r\n')
        } else if (/^DATA/i.test(line)) { data = []; socket.write('354 send data\r\n') }
        else if (/^QUIT/i.test(line)) { socket.end('221 bye\r\n') }
        else socket.write('250 OK\r\n')
      }
    })
  })
  await new Promise<void>((done) => smtp.listen(0, '127.0.0.1', done))
  const address = smtp.address()
  if (!address || typeof address === 'string') throw new Error('No SMTP port')
  const saved: State = { directory, smtpPort: address.port, pid: 0 }
  mkdirSync(join(ROOT, 'registration-results'), { recursive: true })
  writeFileSync(STATE, JSON.stringify(saved))
  const env = environment(saved)
  const run = (name: string, args: string[], input?: string) => execFileSync(join(repository, '.venv/bin', name), args, { cwd: repository, env, input, stdio: ['pipe', 'pipe', 'pipe'] })
  const cleanup = () => {
    const current = state()
    if (current.directory === directory && current.pid > 0) {
      try { process.kill(current.pid, 'SIGTERM') } catch { /* already stopped */ }
    }
    smtp.close()
  }
  try {
    run('alembic', ['upgrade', 'head'])
    run('altero', ['user', 'add', 'operator'])
    run('altero', ['user', 'password', 'operator'], `${PASSWORD}\n${PASSWORD}\n`)
    run('altero', ['user', 'admin', 'operator'])
    await start(saved)
  } catch (error) { cleanup(); throw error }
  return cleanup
}
