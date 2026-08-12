/**
 * What the administration sections share.
 *
 * Less than settings' panel does, and deliberately so: every settings section
 * edits one account, so that panel owns the account and reloads it. These
 * sections each read a different endpoint — what the instance is running, what
 * it costs, who holds an account — and share only the line at the top that
 * says how the last thing went, which is `components/sectionmessages.ts` and
 * belongs to whichever section is showing.
 *
 * Provided per mount rather than held in a module, for the reason
 * `views/settings/panel.ts` gives: state that outlives the component outlives
 * the sign-in too.
 */

import { inject, provide, ref, type InjectionKey, type Ref } from 'vue'

import { ApiError } from '@/api/client'
import { useSectionMessages } from '@/components/sectionmessages'

export interface AdminPanel {
  busy: Ref<boolean>
  notice: Ref<string | null>
  failure: Ref<string | null>
  /** Run one administrative action, reporting whichever way it went. */
  attempt(work: () => Promise<void>, success: string): Promise<void>
}

const KEY: InjectionKey<AdminPanel> = Symbol('admin-panel')

export function message(thrown: unknown): string {
  return thrown instanceof ApiError ? thrown.message : String(thrown)
}

/** Build the shared state and hand it to the sections beneath. */
export function providePanel(): AdminPanel {
  const busy = ref(false)
  const { notice, failure, clear } = useSectionMessages()

  async function attempt(work: () => Promise<void>, success: string): Promise<void> {
    busy.value = true
    clear()
    try {
      await work()
      notice.value = success
    } catch (thrown) {
      failure.value = message(thrown)
    } finally {
      busy.value = false
    }
  }

  const panel: AdminPanel = { busy, notice, failure, attempt }
  provide(KEY, panel)
  return panel
}

/** The shared state, from inside a section. */
export function usePanel(): AdminPanel {
  const panel = inject(KEY)
  if (!panel) {
    throw new Error('An administration section has to be rendered inside AdminView')
  }
  return panel
}
