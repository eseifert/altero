import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError, request } from '@/api/client'
import { useLocaleStore } from '@/stores/locale'
import type { Visibility } from '@/stores/profile'

export interface User {
  id: number
  username: string
  displayName: string
  email: string | null
  emailVerified: boolean
  /** BCP 47 tag, or null to follow the browser. */
  language: string | null
  /** IANA zone, or null to follow the browser. */
  timeZone: string | null
  /** Who may read this account's profile page. Sent to the account itself and
   *  to nobody else; see `stores/profile.ts`. */
  profileVisibility: Visibility
  /** Whether this account administers the instance rather than a library. The
   *  interface shows the administration screens from this alone; every route
   *  behind them checks it again for itself. */
  administrator: boolean
}

interface AuthResponse {
  user: User | null
  needsFactor: string | null
  /** The other factors this account could present instead, if any. */
  alternativeFactors?: string[]
}

interface ServerConfig {
  version: string
  apiVersion: number
  registrationOpen: boolean
  firstAccount: boolean
  secondFactors: string[]
  passwordResetOpen: boolean
  providers: IdentityProvider[]
}

/** A directory this instance accepts a sign-in from. */
export interface IdentityProvider {
  slug: string
  kind: string
  displayName: string
}

export interface RegistrationDetails {
  username: string
  password: string
  email: string
  displayName?: string
}

/**
 * Who is signed in, and how far through signing in they are.
 *
 * Being authenticated is deliberately not the same as holding a session: after
 * a password succeeds but before a second factor is presented, the browser has
 * a real cookie and this store reports `isAuthenticated === false`. The server
 * enforces the same distinction; this mirrors it so the interface cannot show
 * a library that every request for its contents would be refused.
 */
export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const locale = useLocaleStore()

  /* The account's language and time zone travel with the user, so every path
     that sets one hands them over. Signing out drops back to the browser's,
     rather than leaving the next person on this machine in a stranger's
     language. */
  function adoptLocale(account: User | null): void {
    locale.adopt({ language: account?.language ?? null, timeZone: account?.timeZone ?? null })
  }
  const needsFactor = ref<string | null>(null)
  /**
   * The other ways this account could finish signing in.
   *
   * What the "use a code by email instead" button is drawn from, and the
   * answer to a lost authenticator: without it, an account with one it can no
   * longer reach has to find whoever runs the server. Told only to a session
   * that has already produced the password, so it discloses nothing.
   */
  const alternativeFactors = ref<string[]>([])
  const error = ref<string | null>(null)
  const busy = ref(false)
  /** False until the first session check has finished. */
  const ready = ref(false)
  const registrationOpen = ref(false)
  /** True while the instance has no users, which is a different sentence. */
  const firstAccount = ref(false)
  /**
   * Whether the sign-in page offers "forgotten your password?".
   *
   * Asked of the server rather than assumed, because it takes both an operator
   * who turned it on and a relay to send through -- an instance with neither
   * would show a form that can only ever answer 202 and send nothing.
   */
  const passwordResetOpen = ref(false)
  /**
   * The directories the sign-in page should offer a button for.
   *
   * Three fields each and nothing about how any of them is configured: this
   * comes from an endpoint that answers to anybody who loads the page.
   */
  const providers = ref<IdentityProvider[]>([])

  const isAuthenticated = computed(() => user.value !== null)

  function adopt(response: AuthResponse): void {
    user.value = response.user
    adoptLocale(response.user)
    needsFactor.value = response.needsFactor
    alternativeFactors.value = response.alternativeFactors ?? []
    error.value = null
  }

  /** Run `work`, recording the busy flag and any message it produced. */
  async function attempt<T>(work: () => Promise<T>): Promise<T> {
    busy.value = true
    error.value = null
    try {
      return await work()
    } catch (thrown) {
      error.value = thrown instanceof Error ? thrown.message : String(thrown)
      throw thrown
    } finally {
      busy.value = false
    }
  }

  async function restore(): Promise<void> {
    try {
      const response = await request<{ user: User }>('/web/auth/session')
      user.value = response.user
      adoptLocale(response.user)
      needsFactor.value = null
    } catch (thrown) {
      user.value = null
      adoptLocale(null)
      // A 401 here is the ordinary case -- nobody is signed in yet -- and must
      // not be shown as a failure. Anything else is worth reporting, in
      // particular status 0, which means the server never answered at all.
      if (thrown instanceof ApiError && thrown.status !== 401) {
        error.value = thrown.message
      }
    } finally {
      ready.value = true
    }
  }

  async function loadConfig(): Promise<void> {
    try {
      const config = await request<ServerConfig>('/web/config')
      registrationOpen.value = config.registrationOpen
      firstAccount.value = config.firstAccount
      passwordResetOpen.value = config.passwordResetOpen
      providers.value = config.providers ?? []
    } catch {
      // Offering a register link that the server will refuse is worse than
      // not offering one, so an unanswered question means closed. The same
      // reasoning covers the reset link.
      registrationOpen.value = false
      firstAccount.value = false
      passwordResetOpen.value = false
      providers.value = []
    }
  }

  async function login(username: string, password: string): Promise<void> {
    adopt(
      await attempt(() =>
        request<AuthResponse>('/web/auth/login', {
          method: 'POST',
          body: { username, password },
        }),
      ),
    )
  }

  async function register(details: RegistrationDetails): Promise<void> {
    adopt(
      await attempt(() =>
        request<AuthResponse>('/web/auth/register', { method: 'POST', body: details }),
      ),
    )
  }

  /* Which endpoint takes the code depends on where it came from: an
     authenticator app or an inbox. One function either way, because the screen
     asking for it is the same screen. */
  const FACTOR_ENDPOINTS: Record<string, string> = {
    totp: '/web/auth/totp',
    email: '/web/auth/code',
  }

  async function submitFactor(code: string): Promise<void> {
    const endpoint = FACTOR_ENDPOINTS[needsFactor.value ?? 'totp'] ?? FACTOR_ENDPOINTS.totp
    adopt(await attempt(() => request<AuthResponse>(endpoint, { method: 'POST', body: { code } })))
  }

  /** Present a different factor of the same account instead. */
  async function chooseFactor(factor: string): Promise<void> {
    const response = await attempt(() =>
      request<AuthResponse>('/web/auth/factor', { method: 'POST', body: { factor } }),
    )
    needsFactor.value = response.needsFactor
    alternativeFactors.value = response.alternativeFactors ?? []
  }

  /** Ask for another emailed code, which stops the one before it working. */
  async function resendCode(): Promise<void> {
    await attempt(() => request('/web/auth/code/resend', { method: 'POST' }))
  }

  /**
   * Confirm an address from the token in a link.
   *
   * Needs no session: the link is opened in whichever browser happens to be
   * to hand, often not the one that registered, and the token is the whole
   * credential.
   */
  async function verifyEmail(token: string): Promise<void> {
    const response = await attempt(() =>
      request<{ user: User }>('/web/auth/verify', { method: 'POST', body: { token } }),
    )
    // Only adopt the user when one is already signed in; confirming from
    // another browser must not appear to sign that browser in.
    if (user.value) {
      user.value = response.user
      adoptLocale(response.user)
    }
  }

  async function resendVerification(): Promise<void> {
    await request('/web/auth/verify/resend', { method: 'POST' })
  }

  async function logout(): Promise<void> {
    try {
      await request('/web/auth/logout', { method: 'POST' })
    } catch {
      // Deliberately ignored. The session is very likely gone at the server
      // regardless, and keeping the interface populated because the sign-out
      // request failed would leave someone's library on screen.
    } finally {
      user.value = null
      adoptLocale(null)
      needsFactor.value = null
      error.value = null
    }
  }

  return {
    user,
    needsFactor,
    error,
    busy,
    ready,
    registrationOpen,
    firstAccount,
    passwordResetOpen,
    providers,
    isAuthenticated,
    restore,
    loadConfig,
    login,
    register,
    alternativeFactors,
    submitFactor,
    chooseFactor,
    resendCode,
    verifyEmail,
    resendVerification,
    logout,
  }
})
