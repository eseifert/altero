import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { useAuthStore } from './auth'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const ADA = { id: 1, username: 'ada', displayName: 'Ada' }

describe('the auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  describe('restoring on load', () => {
    it('signs the user in when the cookie is still good', async () => {
      requestMock.mockResolvedValue({ user: ADA })
      const auth = useAuthStore()

      await auth.restore()

      expect(auth.user).toEqual(ADA)
      expect(auth.isAuthenticated).toBe(true)
    })

    it('treats a 401 as simply not signed in, not as an error to show', async () => {
      requestMock.mockRejectedValue(new ApiError('Not signed in', 401))
      const auth = useAuthStore()

      await auth.restore()

      expect(auth.user).toBeNull()
      expect(auth.error).toBeNull()
    })

    it('reports a server that is down, which is not the same as being signed out', async () => {
      requestMock.mockRejectedValue(new ApiError('Could not reach the server', 0))
      const auth = useAuthStore()

      await auth.restore()

      expect(auth.user).toBeNull()
      expect(auth.error).toBe('Could not reach the server')
    })

    it('is marked ready afterwards either way, so the router can stop waiting', async () => {
      requestMock.mockRejectedValue(new ApiError('Not signed in', 401))
      const auth = useAuthStore()
      expect(auth.ready).toBe(false)

      await auth.restore()

      expect(auth.ready).toBe(true)
    })
  })

  describe('signing in', () => {
    it('holds the user returned by the server', async () => {
      requestMock.mockResolvedValue({ user: ADA, needsFactor: null })
      const auth = useAuthStore()

      await auth.login('ada', 'correct horse battery staple')

      expect(auth.user).toEqual(ADA)
      expect(auth.isAuthenticated).toBe(true)
    })

    it('posts the credentials to the login endpoint', async () => {
      requestMock.mockResolvedValue({ user: ADA, needsFactor: null })
      const auth = useAuthStore()

      await auth.login('ada', 'correct horse battery staple')

      expect(requestMock).toHaveBeenCalledWith('/web/auth/login', {
        method: 'POST',
        body: { username: 'ada', password: 'correct horse battery staple' },
      })
    })

    it('is not authenticated while a second factor is outstanding', async () => {
      requestMock.mockResolvedValue({ user: null, needsFactor: 'totp' })
      const auth = useAuthStore()

      await auth.login('ada', 'correct horse battery staple')

      expect(auth.needsFactor).toBe('totp')
      expect(auth.isAuthenticated).toBe(false)
    })

    it('keeps the message the server gave for a refusal', async () => {
      requestMock.mockRejectedValue(new ApiError('That username and password do not match', 401))
      const auth = useAuthStore()

      await expect(auth.login('ada', 'wrong')).rejects.toThrow()

      expect(auth.error).toBe('That username and password do not match')
      expect(auth.isAuthenticated).toBe(false)
    })

    it('clears a previous error when a later attempt succeeds', async () => {
      const auth = useAuthStore()
      requestMock.mockRejectedValueOnce(new ApiError('That username and password do not match', 401))
      await auth.login('ada', 'wrong').catch(() => undefined)

      requestMock.mockResolvedValue({ user: ADA, needsFactor: null })
      await auth.login('ada', 'right one this time')

      expect(auth.error).toBeNull()
    })

    it('reports while it is in flight, so the button can be disabled', async () => {
      let release: (value: unknown) => void = () => {}
      requestMock.mockReturnValue(new Promise((resolve) => (release = resolve)))
      const auth = useAuthStore()

      const pending = auth.login('ada', 'correct horse battery staple')
      expect(auth.busy).toBe(true)

      release({ user: ADA, needsFactor: null })
      await pending
      expect(auth.busy).toBe(false)
    })

    it('stops being busy even when the attempt fails', async () => {
      requestMock.mockRejectedValue(new ApiError('nope', 401))
      const auth = useAuthStore()

      await auth.login('ada', 'wrong').catch(() => undefined)

      expect(auth.busy).toBe(false)
    })
  })

  describe('the second factor', () => {
    it('completes the sign-in with the right code', async () => {
      const auth = useAuthStore()
      requestMock.mockResolvedValueOnce({ user: null, needsFactor: 'totp' })
      await auth.login('ada', 'correct horse battery staple')

      requestMock.mockResolvedValueOnce({ user: ADA, needsFactor: null })
      await auth.submitFactor('123456')

      expect(auth.isAuthenticated).toBe(true)
      expect(auth.needsFactor).toBeNull()
    })

    it('leaves the factor outstanding when the code is wrong', async () => {
      const auth = useAuthStore()
      requestMock.mockResolvedValueOnce({ user: null, needsFactor: 'totp' })
      await auth.login('ada', 'correct horse battery staple')

      requestMock.mockRejectedValueOnce(new ApiError('That code is not valid', 401))
      await expect(auth.submitFactor('000000')).rejects.toThrow()

      expect(auth.needsFactor).toBe('totp')
      expect(auth.error).toBe('That code is not valid')
    })
  })

  describe('registering', () => {
    it('signs the new account straight in', async () => {
      requestMock.mockResolvedValue({ user: ADA, needsFactor: null })
      const auth = useAuthStore()

      await auth.register({ username: 'ada', password: 'correct horse battery staple' })

      expect(auth.isAuthenticated).toBe(true)
    })

    it('surfaces why the server refused', async () => {
      requestMock.mockRejectedValue(
        new ApiError('A password must be at least 8 characters', 400),
      )
      const auth = useAuthStore()

      await expect(auth.register({ username: 'ada', password: 'short' })).rejects.toThrow()

      expect(auth.error).toBe('A password must be at least 8 characters')
    })
  })

  describe('signing out', () => {
    it('forgets the user', async () => {
      const auth = useAuthStore()
      requestMock.mockResolvedValueOnce({ user: ADA, needsFactor: null })
      await auth.login('ada', 'correct horse battery staple')

      requestMock.mockResolvedValueOnce(null)
      await auth.logout()

      expect(auth.user).toBeNull()
      expect(auth.isAuthenticated).toBe(false)
    })

    it('forgets the user even if the request fails', async () => {
      const auth = useAuthStore()
      requestMock.mockResolvedValueOnce({ user: ADA, needsFactor: null })
      await auth.login('ada', 'correct horse battery staple')

      requestMock.mockRejectedValueOnce(new ApiError('Could not reach the server', 0))
      await auth.logout()

      // The session may well be gone server-side; staying "signed in" in the
      // interface would be a lie and would leave the screen populated.
      expect(auth.user).toBeNull()
    })
  })

  describe('server configuration', () => {
    it('learns whether registration is open', async () => {
      requestMock.mockResolvedValue({
        registrationOpen: true,
        secondFactors: ['totp'],
        version: '0.1.0',
      })
      const auth = useAuthStore()

      await auth.loadConfig()

      expect(auth.registrationOpen).toBe(true)
    })

    it('assumes registration is closed when the server cannot be asked', async () => {
      requestMock.mockRejectedValue(new ApiError('Could not reach the server', 0))
      const auth = useAuthStore()

      await auth.loadConfig()

      expect(auth.registrationOpen).toBe(false)
    })
  })
})
