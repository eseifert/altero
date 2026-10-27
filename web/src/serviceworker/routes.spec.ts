import { describe, expect, it } from 'vitest'

import { cacheName, route } from './routes'

const ORIGIN = 'https://altero.example'

function ask(path: string, options: { method?: string; mode?: string; origin?: string } = {}) {
  return route(
    { url: `${options.origin ?? ORIGIN}${path}`, method: options.method ?? 'GET', mode: options.mode ?? 'cors' },
    ORIGIN,
  )
}

describe('what the service worker keeps', () => {
  it('keeps the fingerprinted files', () => {
    expect(ask('/app/assets/index-abc123.js')).toBe('asset')
    expect(ask('/app/assets/plex-sans-latin-400.woff2')).toBe('asset')
  })

  it('keeps the page for every route of the app, as one shell', () => {
    expect(ask('/app/', { mode: 'navigate' })).toBe('shell')
    expect(ask('/app', { mode: 'navigate' })).toBe('shell')
    expect(ask('/app/settings', { mode: 'navigate' })).toBe('shell')
  })

  it('never keeps the browser’s own API, the v3 API or the feed', () => {
    expect(ask('/web/libraries/1/items')).toBe('pass')
    expect(ask('/web/libraries/1/events')).toBe('pass')
    expect(ask('/web/auth/session', { mode: 'navigate' })).toBe('pass')
    expect(ask('/users/1/items')).toBe('pass')
    expect(ask('/stream')).toBe('pass')
  })

  it('leaves alone what is not a read, or not from here', () => {
    expect(ask('/app/assets/index-abc123.js', { method: 'POST' })).toBe('pass')
    expect(ask('/app/assets/x.js', { origin: 'https://elsewhere.example' })).toBe('pass')
    // Outside the scope it controls, the root is the API's.
    expect(ask('/', { mode: 'navigate' })).toBe('pass')
    expect(ask('/application', { mode: 'navigate' })).toBe('pass')
  })

  it('names one cache per build', () => {
    expect(cacheName('a7fd026c')).toBe('altero-a7fd026c')
  })
})
