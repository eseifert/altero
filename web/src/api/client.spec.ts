import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, request } from './client'

function respond(body: unknown, init: ResponseInit = {}): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  })
}

describe('the api client', () => {
  beforeEach(() => {
    document.cookie = 'altero_csrf=token-from-cookie; path=/'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends cookies, which is the whole authentication mechanism', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/web/auth/session')

    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'same-origin' })
  })

  it('echoes the csrf cookie in a header on an unsafe request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/web/auth/logout', { method: 'POST' })

    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.get('X-CSRF-Token')).toBe('token-from-cookie')
  })

  it('does not bother with the header on a safe request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/web/config')

    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.get('X-CSRF-Token')).toBeNull()
  })

  it('picks the right cookie when the browser holds several', async () => {
    document.cookie = 'other=nope; path=/'
    document.cookie = 'altero_csrf_extra=wrong; path=/'
    const fetchMock = vi.fn().mockResolvedValue(respond({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/web/auth/logout', { method: 'POST' })

    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.get('X-CSRF-Token')).toBe('token-from-cookie')
  })

  it('serialises a body as json', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/web/auth/login', { method: 'POST', body: { username: 'ada' } })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.body).toBe('{"username":"ada"}')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  it('returns the parsed body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ user: { username: 'ada' } })))

    await expect(request('/web/auth/session')).resolves.toEqual({ user: { username: 'ada' } })
  })

  it('returns null for an empty response rather than failing to parse it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(null, { status: 204 })))

    await expect(request('/web/auth/logout', { method: 'POST' })).resolves.toBeNull()
  })

  it('raises the server message, which is what the form shows the user', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(respond({ message: 'That username and password do not match' }, { status: 401 })),
    )

    await expect(request('/web/auth/login', { method: 'POST' })).rejects.toThrow(
      'That username and password do not match',
    )
  })

  it('carries the status so a 401 can be told from a 500', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ message: 'Not signed in' }, { status: 401 })))

    await expect(request('/web/auth/session')).rejects.toMatchObject({ status: 401 })
  })

  it('still raises something readable when the error body is not json', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>502</html>', { status: 502 })),
    )

    const error = await request('/web/config').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(502)
    expect((error as ApiError).message).toBeTruthy()
  })

  it('reports a network failure as an ApiError rather than a raw TypeError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    const error = await request('/web/config').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(0)
  })
})
