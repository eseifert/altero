/**
 * The browser half of a passkey ceremony.
 *
 * WebAuthn deals in `ArrayBuffer`s and JSON does not, so everything crossing
 * the wire is base64url and everything reaching `navigator.credentials` is
 * bytes. That conversion is all this module is, and it lives on its own
 * because getting it wrong fails deep inside the browser with an error that
 * says nothing useful.
 */
import { request } from '@/api/client'

/** Whether this browser can do any of it at all. */
export function available(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.PublicKeyCredential !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    navigator.credentials !== undefined
  )
}

/* Returns an ArrayBuffer rather than a view: `BufferSource` will not take a
   `Uint8Array<ArrayBufferLike>`, and every one of these values goes straight
   into a WebAuthn option. */
function toBytes(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4))
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes.buffer
}

function toBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** The server's options, with the byte-valued fields decoded. */
function decodeCreationOptions(options: Record<string, unknown>): PublicKeyCredentialCreationOptions {
  const user = options.user as Record<string, unknown>
  return {
    ...(options as unknown as PublicKeyCredentialCreationOptions),
    challenge: toBytes(options.challenge as string),
    user: { ...(user as unknown as PublicKeyCredentialUserEntity), id: toBytes(user.id as string) },
    excludeCredentials: ((options.excludeCredentials ?? []) as Record<string, unknown>[]).map(
      (entry) => ({
        ...entry,
        type: 'public-key' as const,
        id: toBytes(entry.id as string),
      }),
    ),
  }
}

function decodeRequestOptions(options: Record<string, unknown>): PublicKeyCredentialRequestOptions {
  return {
    ...(options as unknown as PublicKeyCredentialRequestOptions),
    challenge: toBytes(options.challenge as string),
    allowCredentials: ((options.allowCredentials ?? []) as Record<string, unknown>[]).map(
      (entry) => ({
        ...entry,
        type: 'public-key' as const,
        id: toBytes(entry.id as string),
      }),
    ),
  }
}

function encodeRegistration(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: toBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64Url(response.clientDataJSON),
      attestationObject: toBase64Url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  }
}

function encodeAuthentication(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response as AuthenticatorAssertionResponse
  return {
    id: credential.id,
    rawId: toBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64Url(response.clientDataJSON),
      authenticatorData: toBase64Url(response.authenticatorData),
      signature: toBase64Url(response.signature),
      userHandle: response.userHandle ? toBase64Url(response.userHandle) : null,
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  }
}

/**
 * Thrown when the person cancelled, or the browser refused.
 *
 * Distinguished from a server error because there is nothing to report: they
 * closed the prompt, and a red message about it is noise.
 */
export class Cancelled extends Error {}

async function ask<T>(work: () => Promise<T | null>): Promise<T> {
  let credential: T | null
  try {
    credential = await work()
  } catch (thrown) {
    // NotAllowedError is both "cancelled" and "timed out", and the browser
    // deliberately does not say which -- telling them apart would leak
    // whether a credential existed.
    if (thrown instanceof Error && thrown.name === 'NotAllowedError') {
      throw new Cancelled(thrown.message)
    }
    throw thrown
  }
  if (credential === null) throw new Cancelled('No passkey was produced')
  return credential
}

/**
 * Enrol a passkey on the account that is signed in.
 *
 * The password comes first: a passkey is a way *in*, so adding one asks for
 * proof exactly as making an API key does. Asking before the authenticator is
 * touched means a refusal does not arrive after a fingerprint.
 */
export async function enrol(name: string, currentPassword: string): Promise<void> {
  const options = await request<Record<string, unknown>>('/web/account/passkeys/options', {
    method: 'POST',
    body: { currentPassword },
  })

  const credential = await ask(() =>
    navigator.credentials.create({ publicKey: decodeCreationOptions(options) }),
  )

  await request('/web/account/passkeys', {
    method: 'POST',
    body: { credential: encodeRegistration(credential as PublicKeyCredential), name },
  })
}

/**
 * Sign in with whatever passkey the browser holds for this site.
 *
 * No username is asked for anywhere in this flow: the assertion says who it
 * is, which is what makes the sign-in page unable to answer whether an
 * account exists.
 */
export async function signIn(): Promise<Record<string, unknown>> {
  const options = await request<Record<string, unknown>>('/web/auth/passkey/options', {
    method: 'POST',
  })

  const credential = await ask(() =>
    navigator.credentials.get({ publicKey: decodeRequestOptions(options) }),
  )

  return await request('/web/auth/passkey/verify', {
    method: 'POST',
    body: { credential: encodeAuthentication(credential as PublicKeyCredential) },
  })
}

/** Answer an outstanding second factor with a passkey instead of a code. */
export async function satisfyFactor(): Promise<Record<string, unknown>> {
  const options = await request<Record<string, unknown>>('/web/auth/passkey/options', {
    method: 'POST',
  })

  const credential = await ask(() =>
    navigator.credentials.get({ publicKey: decodeRequestOptions(options) }),
  )

  return await request('/web/auth/passkey/factor', {
    method: 'POST',
    body: { credential: encodeAuthentication(credential as PublicKeyCredential) },
  })
}
