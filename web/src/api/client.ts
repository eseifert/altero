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

  /** What the refusal was about, when the server said: the fields a change
   *  of item type would lose, for one. */
  readonly data: Record<string, unknown> | undefined

  constructor(
    message: string,
    status: number,
    options?: ErrorOptions & { data?: Record<string, unknown> },
  ) {
    super(message, options)
    this.name = 'ApiError'
    this.status = status
    this.data = options?.data
  }
}

export interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
  /** A write precondition, alongside the session cookie and CSRF token. */
  headers?: Record<string, string>
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
  { method = 'GET', body, signal, headers: extraHeaders }: RequestOptions = {},
): Promise<T> {
  // A form is sent as it is: it carries a file, and the browser has to write
  // the Content-Type itself because only it knows the multipart boundary.
  // Setting the header here would produce a body the server cannot parse.
  const form = body instanceof FormData

  const headers = new Headers(extraHeaders)
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
    const data = isRecord(payload) && isRecord(payload.data) ? payload.data : undefined
    throw new ApiError(message, response.status, { data })
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

export interface UploadOptions {
  method?: 'POST' | 'PUT'
  /** Headers besides the CSRF token and the file's own type: a precondition. */
  headers?: Record<string, string>
  /** Told how many of the file's bytes have gone, as they go. */
  onProgress?: (sent: number, total: number) => void
  signal?: AbortSignal
}

/**
 * Send ``file`` as the body of a request, reporting how far it has got.
 *
 * `XMLHttpRequest` rather than `fetch`, which says nothing about an upload
 * until it is over -- and a file of a few hundred megabytes on a slow line is
 * minutes of a page that looks as if it has stopped. The file is the body as
 * it is, with its own type as `Content-Type`, which is what the server asks
 * for: a form would be written to disk twice on the way in.
 *
 * A cancelled upload rejects with an {@link ApiError} of status 0 whose
 * `cancelled` is set, so a caller can tell somebody changing their mind from a
 * connection that dropped.
 */
export function upload<T = unknown>(
  path: string,
  file: Blob,
  { method = 'POST', headers = {}, onProgress, signal }: UploadOptions = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    // Same-origin, so the session cookie goes with it unasked.
    xhr.open(method, path)
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream')
    const token = readCookie(CSRF_COOKIE)
    if (token) xhr.setRequestHeader(CSRF_HEADER, token)
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded, event.total)
    }
    xhr.onload = () => {
      const payload = parse(xhr.responseText)
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as T)
        return
      }
      const message =
        (isRecord(payload) && typeof payload.message === 'string' && payload.message) ||
        `The server answered ${xhr.status}`
      const data = isRecord(payload) && isRecord(payload.data) ? payload.data : undefined
      reject(new ApiError(message, xhr.status, { data }))
    }
    xhr.onerror = () => reject(new ApiError('Could not reach the server', 0))
    xhr.onabort = () => reject(Object.assign(new ApiError('Cancelled', 0), { cancelled: true }))

    if (signal?.aborted) {
      reject(Object.assign(new ApiError('Cancelled', 0), { cancelled: true }))
      return
    }
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(file)
  })
}

/** Whether ``error`` is an upload the person cancelled. */
export function isCancelled(error: unknown): boolean {
  return error instanceof ApiError && (error as ApiError & { cancelled?: boolean }).cancelled === true
}

function parse(text: string): unknown {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}
