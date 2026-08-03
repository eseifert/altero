import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError, request } from '@/api/client'

export interface User {
  id: number
  username: string
  displayName: string
}

interface AuthResponse {
  user: User | null
  needsFactor: string | null
}

interface ServerConfig {
  version: string
  apiVersion: number
  registrationOpen: boolean
  secondFactors: string[]
}

export interface RegistrationDetails {
  username: string
  password: string
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
  const needsFactor = ref<string | null>(null)
  const error = ref<string | null>(null)
  const busy = ref(false)
  /** False until the first session check has finished. */
  const ready = ref(false)
  const registrationOpen = ref(false)

  const isAuthenticated = computed(() => user.value !== null)

  function adopt(response: AuthResponse): void {
    user.value = response.user
    needsFactor.value = response.needsFactor
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
      needsFactor.value = null
    } catch (thrown) {
      user.value = null
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
    } catch {
      // Offering a register link that the server will refuse is worse than
      // not offering one, so an unanswered question means closed.
      registrationOpen.value = false
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

  async function submitFactor(code: string): Promise<void> {
    adopt(
      await attempt(() =>
        request<AuthResponse>('/web/auth/totp', { method: 'POST', body: { code } }),
      ),
    )
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
    isAuthenticated,
    restore,
    loadConfig,
    login,
    register,
    submitFactor,
    logout,
  }
})
