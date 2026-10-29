import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, isCancelled, request, upload } from './client'

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

  it('carries a version precondition together with the csrf token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await request('/web/libraries/1/items/merge', {
      method: 'POST', body: {}, headers: { 'If-Unmodified-Since-Version': '17' },
    })
    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.get('If-Unmodified-Since-Version')).toBe('17')
    expect(headers.get('X-CSRF-Token')).toBe('token-from-cookie')
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

/** An `XMLHttpRequest` that answers when told to, and remembers what it was sent. */
class FakeRequest {
  static last: FakeRequest
  method = ''
  url = ''
  headers: Record<string, string> = {}
  body: unknown = null
  status = 0
  responseText = ''
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() {
    FakeRequest.last = this
  }

  open(method: string, url: string): void {
    this.method = method
    this.url = url
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value
  }

  send(body: unknown): void {
    this.body = body
  }

  abort(): void {
    this.onabort?.()
  }

  answer(status: number, body: unknown): void {
    this.status = status
    this.responseText = JSON.stringify(body)
    this.onload?.()
  }
}

describe('uploading a file', () => {
  beforeEach(() => {
    document.cookie = 'altero_csrf=token-from-cookie; path=/'
    vi.stubGlobal('XMLHttpRequest', FakeRequest)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the file itself, typed as the file, with the CSRF token', async () => {
    const file = new File(['%PDF'], 'paper.pdf', { type: 'application/pdf' })

    const sent = upload('/web/libraries/1/attachments?filename=paper.pdf', file, {
      headers: { 'If-Match': 'abc' },
    })
    FakeRequest.last.answer(201, { key: 'ABCD2345' })

    expect(await sent).toEqual({ key: 'ABCD2345' })
    expect(FakeRequest.last.method).toBe('POST')
    expect(FakeRequest.last.body).toBe(file)
    expect(FakeRequest.last.headers).toMatchObject({
      'Content-Type': 'application/pdf',
      'X-CSRF-Token': 'token-from-cookie',
      'If-Match': 'abc',
    })
  })

  it('calls a file of no known type octet-stream', async () => {
    const sent = upload('/up', new File(['x'], 'x'))
    FakeRequest.last.answer(201, {})
    await sent

    expect(FakeRequest.last.headers['Content-Type']).toBe('application/octet-stream')
  })

  it('reports progress', async () => {
    const seen: number[] = []
    const sent = upload('/up', new File(['abcd'], 'a'), { onProgress: (done) => seen.push(done) })
    FakeRequest.last.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 4 } as ProgressEvent)
    FakeRequest.last.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 4 } as ProgressEvent)
    FakeRequest.last.answer(201, {})
    await sent

    expect(seen).toEqual([2, 4])
  })

  it('turns a refusal into the server’s message', async () => {
    const sent = upload('/up', new File(['x'], 'x'))
    FakeRequest.last.answer(413, { message: 'File is too large' })

    const error = await sent.catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(413)
    expect((error as ApiError).message).toBe('File is too large')
    expect(isCancelled(error)).toBe(false)
  })

  it('says when it was cancelled', async () => {
    const controller = new AbortController()
    const sent = upload('/up', new File(['x'], 'x'), { signal: controller.signal })
    controller.abort()

    expect(isCancelled(await sent.catch((e: unknown) => e))).toBe(true)
  })
})
