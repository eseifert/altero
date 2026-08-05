/**
 * The one place that talks to the server.
 *
 * Authentication is entirely the session cookie, so nothing here holds a
 * token: `credentials: 'same-origin'` is the whole of it. What this does carry
 * is the CSRF header, read from the cookie the server set for exactly that
 * purpose -- a page on another origin can make the browser send the cookie but
 * cannot read it, so it cannot produce this header.
 */

/** The CSRF cookie the server sets. Readable by script on purpose. */
const CSRF_COOKIE = 'altero_csrf'

const CSRF_HEADER = 'X-CSRF-Token'

/** Methods that do not change anything, and so need no CSRF token. */
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export class ApiError extends Error {
  /** The HTTP status, or 0 when the request never reached the server. */
  readonly status: number

  constructor(message: string, status: number, options?: ErrorOptions) {
    super(message, options)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
}

/** Return one cookie's value, matching the whole name rather than a prefix. */
export function readCookie(name: string): string | null {
  const match = document.cookie
    .split('; ')
    .map((pair) => pair.split('='))
    .find(([key]) => key === name)
  return match ? decodeURIComponent(match.slice(1).join('=')) : null
}

export async function request<T = unknown>(
  path: string,
  { method = 'GET', body, signal }: RequestOptions = {},
): Promise<T> {
  // A form is sent as it is: it carries a file, and the browser has to write
  // the Content-Type itself because only it knows the multipart boundary.
  // Setting the header here would produce a body the server cannot parse.
  const form = body instanceof FormData

  const headers = new Headers()
  if (body !== undefined && !form) {
    headers.set('Content-Type', 'application/json')
  }
  if (!SAFE_METHODS.has(method.toUpperCase())) {
    const token = readCookie(CSRF_COOKIE)
    if (token) {
      headers.set(CSRF_HEADER, token)
    }
  }

  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      signal,
      // The cookie is the credential. Same-origin rather than include: the
      // interface is served by the same application it talks to.
      credentials: 'same-origin',
      body: body === undefined ? undefined : form ? (body as FormData) : JSON.stringify(body),
    })
  } catch (cause) {
    // A dropped connection or a stopped server. Status 0 marks "never got an
    // answer", which the caller shows differently from a refusal.
    throw new ApiError('Could not reach the server', 0, { cause })
  }

  const payload = await readBody(response)

  if (!response.ok) {
    const message =
      (isRecord(payload) && typeof payload.message === 'string' && payload.message) ||
      `The server answered ${response.status}`
    throw new ApiError(message, response.status)
  }

  return payload as T
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null
  }
  const text = await response.text()
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text)
  } catch {
    // An error page from a proxy in front of the application, or a crash that
    // never reached our own handler. The status still means something.
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
