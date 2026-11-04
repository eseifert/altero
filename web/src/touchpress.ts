import { onScopeDispose } from 'vue'

/** Touch feedback supplements native :active without canceling any input. */
export function useTouchPress(): void {
  let pressed: { button: HTMLButtonElement; pointer: number } | null = null

  function clear(): void {
    pressed?.button.removeAttribute('data-touch-pressed')
    pressed = null
  }

  function listen<K extends keyof WindowEventMap>(name: K, callback: (event: WindowEventMap[K]) => void): void {
    window.addEventListener(name, callback, { capture: true, passive: true })
    onScopeDispose(() => window.removeEventListener(name, callback, true))
  }

  listen('pointerdown', (event) => {
    if (event.pointerType !== 'touch' || !event.isPrimary || event.button !== 0) return
    clear()
    const button = event.target instanceof Element
      ? event.target.closest('button.app-button, button.icon-button') : null
    if (!(button instanceof HTMLButtonElement) || button.disabled) return
    pressed = { button, pointer: event.pointerId }
    button.setAttribute('data-touch-pressed', '')
  })

  const released = (event: PointerEvent) => {
    if (event.pointerId === pressed?.pointer) clear()
  }
  listen('pointerup', released)
  listen('pointercancel', released)
  listen('lostpointercapture', released)
  listen('pointermove', (event) => {
    if (event.pointerId === pressed?.pointer &&
        !pressed.button.contains(document.elementFromPoint(event.clientX, event.clientY))) clear()
  })
  listen('scroll', clear)
  listen('blur', (event) => { if (event.target === event.currentTarget) clear() })
  onScopeDispose(clear)
}
