/**
 * What the settings sections share.
 *
 * The screen is one page split into sections rather than five screens: the
 * account is loaded once, and whichever section reports success or failure
 * reports it in the same place, at the top, where the eye already is. So the
 * shell owns that state and the sections reach it through here.
 *
 * Provided per mount rather than held in a module: state that outlives the
 * component outlives the sign-in too, and the next account would open settings
 * to the previous one's name for as long as the first request took.
 */

import { inject, provide, ref, type InjectionKey, type Ref } from 'vue'

import { ApiError, request } from '@/api/client'
import type { User } from '@/stores/auth'

export interface AccountPayload {
  user: User
  totpEnabled: boolean
  sessions: SessionEntry[]
}

export interface SessionEntry {
  id: number
  userAgent: string
  created: string
  lastSeen: string
  current: boolean
}

export interface SettingsPanel {
  account: Ref<AccountPayload | null>
  busy: Ref<boolean>
  notice: Ref<string | null>
  failure: Ref<string | null>
  /** Re-read the account. Called after anything that changes it. */
  reload(): Promise<void>
  /** Run one settings action, reporting whichever way it went. */
  attempt(work: () => Promise<void>, success: string): Promise<void>
}

const KEY: InjectionKey<SettingsPanel> = Symbol('settings-panel')

export function message(thrown: unknown): string {
  return thrown instanceof ApiError ? thrown.message : String(thrown)
}

/** Build the shared state and hand it to the sections beneath. */
export function providePanel(): SettingsPanel {
  const account = ref<AccountPayload | null>(null)
  const busy = ref(false)
  const notice = ref<string | null>(null)
  const failure = ref<string | null>(null)

  async function reload(): Promise<void> {
    try {
      account.value = await request<AccountPayload>('/web/account')
    } catch (thrown) {
      failure.value = message(thrown)
    }
  }

  async function attempt(work: () => Promise<void>, success: string): Promise<void> {
    busy.value = true
    notice.value = null
    failure.value = null
    try {
      await work()
      notice.value = success
      await reload()
    } catch (thrown) {
      failure.value = message(thrown)
    } finally {
      busy.value = false
    }
  }

  const panel: SettingsPanel = { account, busy, notice, failure, reload, attempt }
  provide(KEY, panel)
  return panel
}

/** The shared state, from inside a section. */
export function usePanel(): SettingsPanel {
  const panel = inject(KEY)
  if (!panel) {
    throw new Error('A settings section has to be rendered inside SettingsView')
  }
  return panel
}
