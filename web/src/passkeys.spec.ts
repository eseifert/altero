// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as passkeys from './passkeys'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

/** base64url, as everything crossing this boundary is. */
function b64(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function withWebAuthn(credentials: Partial<CredentialsContainer>): void {
  Object.defineProperty(window, 'PublicKeyCredential', {
    value: function PublicKeyCredential() {},
    writable: true,
    configurable: true,
  })
  Object.defineProperty(navigator, 'credentials', {
    value: credentials,
    writable: true,
    configurable: true,
  })
}

function withoutWebAuthn(): void {
  Object.defineProperty(window, 'PublicKeyCredential', {
    value: undefined,
    writable: true,
    configurable: true,
  })
}

/** What `navigator.credentials.get` hands back. */
function assertion() {
  return {
    id: 'a-credential-id',
    rawId: new Uint8Array([1, 2, 3]).buffer,
    type: 'public-key',
    response: {
      clientDataJSON: new Uint8Array([4, 5]).buffer,
      authenticatorData: new Uint8Array([6, 7]).buffer,
      signature: new Uint8Array([8, 9]).buffer,
      userHandle: null,
    },
    getClientExtensionResults: () => ({}),
  }
}

beforeEach(() => {
  requestMock.mockReset()
  requestMock.mockResolvedValue({})
})

describe('whether passkeys can be used at all', () => {
  it('says no where the browser has no WebAuthn', () => {
    withoutWebAuthn()

    expect(passkeys.available()).toBe(false)
  })

  it('says yes where it does', () => {
    withWebAuthn({ get: vi.fn(), create: vi.fn() })

    expect(passkeys.available()).toBe(true)
  })
})

describe('signing in', () => {
  it('decodes the challenge into bytes for the browser', async () => {
    /* The server sends base64url and `navigator.credentials` takes an
       ArrayBuffer; getting that wrong fails deep inside the browser with an
       error that says nothing. */
    const get = vi.fn().mockResolvedValue(assertion())
    withWebAuthn({ get })
    requestMock.mockResolvedValueOnce({ challenge: b64(new Uint8Array([10, 20, 30])) })

    await passkeys.signIn()

    const options = get.mock.calls[0][0].publicKey
    expect(new Uint8Array(options.challenge)).toEqual(new Uint8Array([10, 20, 30]))
  })

  it('sends no username anywhere', async () => {
    /* The whole flow: the assertion says who it is, so the page cannot be
       used to ask whether an account exists. */
    withWebAuthn({ get: vi.fn().mockResolvedValue(assertion()) })
    requestMock.mockResolvedValueOnce({ challenge: b64(new Uint8Array([1])) })

    await passkeys.signIn()

    const sent = JSON.stringify(requestMock.mock.calls)
    expect(sent).not.toContain('username')
  })

  it('encodes what the authenticator produced back to base64url', async () => {
    withWebAuthn({ get: vi.fn().mockResolvedValue(assertion()) })
    requestMock.mockResolvedValueOnce({ challenge: b64(new Uint8Array([1])) })

    await passkeys.signIn()

    const [path, options] = requestMock.mock.calls[1]
    expect(path).toBe('/web/auth/passkey/verify')
    expect(options.body.credential.response.signature).toBe(b64(new Uint8Array([8, 9])))
  })

  it('treats a cancelled prompt as its own thing', async () => {
    /* They closed the dialog. A red message about it is noise, so the caller
       has to be able to tell this from a real failure. */
    const refusal = new Error('The operation either timed out or was not allowed')
    refusal.name = 'NotAllowedError'
    withWebAuthn({ get: vi.fn().mockRejectedValue(refusal) })
    requestMock.mockResolvedValueOnce({ challenge: b64(new Uint8Array([1])) })

    await expect(passkeys.signIn()).rejects.toBeInstanceOf(passkeys.Cancelled)
  })

  it('lets a real failure through', async () => {
    withWebAuthn({ get: vi.fn().mockRejectedValue(new Error('something else went wrong')) })
    requestMock.mockResolvedValueOnce({ challenge: b64(new Uint8Array([1])) })

    await expect(passkeys.signIn()).rejects.not.toBeInstanceOf(passkeys.Cancelled)
  })

  it('treats a null credential as a cancellation', async () => {
    withWebAuthn({ get: vi.fn().mockResolvedValue(null) })
    requestMock.mockResolvedValueOnce({ challenge: b64(new Uint8Array([1])) })

    await expect(passkeys.signIn()).rejects.toBeInstanceOf(passkeys.Cancelled)
  })
})

describe('enrolling', () => {
  it('decodes the user handle as well as the challenge', async () => {
    /* Both are byte-valued, and a user handle left as a string produces a
       passkey the browser will not later offer. */
    const create = vi.fn().mockResolvedValue({
      id: 'new-credential',
      rawId: new Uint8Array([1]).buffer,
      type: 'public-key',
      response: {
        clientDataJSON: new Uint8Array([2]).buffer,
        attestationObject: new Uint8Array([3]).buffer,
        getTransports: () => ['internal'],
      },
      getClientExtensionResults: () => ({}),
    })
    withWebAuthn({ create })
    requestMock.mockResolvedValueOnce({
      challenge: b64(new Uint8Array([9])),
      user: { id: b64(new Uint8Array([7])), name: 'ada', displayName: 'Ada' },
      excludeCredentials: [{ id: b64(new Uint8Array([5])) }],
    })

    await passkeys.enrol('Work laptop', 'correct horse battery staple')

    const options = create.mock.calls[0][0].publicKey
    expect(new Uint8Array(options.user.id)).toEqual(new Uint8Array([7]))
    expect(new Uint8Array(options.excludeCredentials[0].id)).toEqual(new Uint8Array([5]))
    expect(options.excludeCredentials[0].type).toBe('public-key')
  })

  it('asks for the password before the authenticator is touched', async () => {
    /* A passkey is a way *in*, so adding one takes proof -- and asking first
       means a refusal does not arrive after a fingerprint. */
    const create = vi.fn().mockResolvedValue(null)
    withWebAuthn({ create })
    requestMock.mockResolvedValueOnce({
      challenge: b64(new Uint8Array([9])),
      user: { id: b64(new Uint8Array([7])), name: 'ada', displayName: 'Ada' },
    })

    await passkeys.enrol('Work laptop', 'correct horse battery staple').catch(() => undefined)

    expect(requestMock.mock.calls[0]).toEqual([
      '/web/account/passkeys/options',
      { method: 'POST', body: { currentPassword: 'correct horse battery staple' } },
    ])
  })

  it('sends the name along with the credential', async () => {
    withWebAuthn({
      create: vi.fn().mockResolvedValue({
        id: 'new-credential',
        rawId: new Uint8Array([1]).buffer,
        type: 'public-key',
        response: {
          clientDataJSON: new Uint8Array([2]).buffer,
          attestationObject: new Uint8Array([3]).buffer,
          getTransports: () => [],
        },
        getClientExtensionResults: () => ({}),
      }),
    })
    requestMock.mockResolvedValueOnce({
      challenge: b64(new Uint8Array([9])),
      user: { id: b64(new Uint8Array([7])), name: 'ada', displayName: 'Ada' },
    })

    await passkeys.enrol('Work laptop', 'correct horse battery staple')

    const [path, options] = requestMock.mock.calls[1]
    expect(path).toBe('/web/account/passkeys')
    expect(options.body.name).toBe('Work laptop')
  })
})
