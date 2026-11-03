import { nextTick, ref } from 'vue'

import { retire, revive } from '@/retiring'

/** Retire rows until their height/opacity transition ends, with keyboard recovery. */
export function useRowTransitions(focusEmpty: () => void) {
  const leaving = ref(0)
  const pending = new Set<Element>()

  function beforeLeave(element: Element): void {
    if (pending.has(element)) return
    pending.add(element)
    leaving.value = pending.size
    const row = element as HTMLElement
    const list = row.parentElement
    const active = document.activeElement
    const ownedFocus = active instanceof HTMLElement && row.contains(active)
    const focusedRow = active?.closest('[data-row]') ?? row.querySelector('[data-row]')
    const index = list ? [...list.querySelectorAll('[data-row]')].indexOf(focusedRow!) : 0
    row.style.setProperty('--leaving-row-height', `${row.getBoundingClientRect().height}px`)
    retire(row)

    if (ownedFocus) void nextTick(() => {
      if (!list?.isConnected) return
      // A person may already have moved to another control. Never steal it.
      if (document.activeElement !== document.body && !row.contains(document.activeElement)) return
      const remaining = [...list.querySelectorAll<HTMLElement>('[data-row]')]
        .filter((button) => !button.closest('[inert]'))
      const next = remaining[Math.min(Math.max(index, 0), remaining.length - 1)]
      if (next) next.focus()
      else focusEmpty()
    })
  }

  function afterLeave(element: Element): void {
    if (!pending.delete(element)) return
    revive(element)
    ;(element as HTMLElement).style.removeProperty('--leaving-row-height')
    leaving.value = pending.size
  }

  return { leaving, beforeLeave, afterLeave }
}
