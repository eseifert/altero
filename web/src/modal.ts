import { onBeforeUnmount, onMounted, type ShallowRef } from 'vue'

/**
 * Opening a `<dialog>` as a modal, including where there is no such thing.
 *
 * `showModal` does four things worth having: it puts the dialog in the top
 * layer, paints a backdrop, closes on Escape, and keeps the focus inside. It
 * arrived in Safari 15.4, and this interface is meant to work on an iPhone SE
 * that stopped at iOS 14.6 — where `<dialog>` is an unknown element, drawn as
 * an ordinary block in the middle of the page, and `showModal` is not a
 * function at all.
 *
 * So the element stays a `<dialog>` — one component tree, one set of tests,
 * and the good behaviour wherever the browser has it — and where it does not,
 * the four things are done here instead. The marker attribute is what the
 * stylesheet hangs the fallback's own top layer and backdrop on.
 */

/** Whether the browser can open a dialog as a modal itself. */
export function supportsModal(): boolean {
  return (
    typeof HTMLDialogElement === 'function' &&
    typeof HTMLDialogElement.prototype.showModal === 'function'
  )
}

/** What the focus trap will move between. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Open ``dialog`` while the component is mounted, and close it after.
 *
 * ``onCancel`` is Escape, which the native dialog reports as a `cancel` event
 * and the fallback has to notice for itself.
 */
export function useModal(dialog: ShallowRef<HTMLDialogElement | null>, onCancel: () => void): void {
  /* Where the focus was, so it can be put back. The browser does this for a
     native modal; a dialog that leaves the focus on `<body>` leaves a keyboard
     at the top of the document. */
  let restore: HTMLElement | null = null

  /* No visibility filter: the selector already skips what is disabled, and a
     dialog here shows everything it holds. Asking whether an element is drawn
     means measuring it, which is a layout on every Tab. */
  function focusables(): HTMLElement[] {
    return [...(dialog.value?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])]
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault()
      onCancel()
      return
    }
    if (event.key !== 'Tab') return

    /* The trap. Without it, tabbing past the last control walks into the page
       behind the dialog, which is still there and still clickable. */
    const inside = focusables()
    if (!inside.length) return
    const first = inside[0]
    const last = inside[inside.length - 1]
    const active = document.activeElement

    if (event.shiftKey && (active === first || !dialog.value?.contains(active))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  onMounted(() => {
    const element = dialog.value
    if (!element) return

    restore = document.activeElement instanceof HTMLElement ? document.activeElement : null

    if (supportsModal()) {
      element.showModal()
      return
    }

    element.setAttribute('open', '')
    element.setAttribute('data-modal-fallback', '')
    element.setAttribute('aria-modal', 'true')
    element.setAttribute('role', 'dialog')
    /* The page behind a modal must not scroll under it, which is the last of
       the things the top layer would have taken care of. */
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKeydown, true)
  })

  onBeforeUnmount(() => {
    if (!supportsModal()) {
      document.removeEventListener('keydown', onKeydown, true)
      document.body.style.overflow = ''
    }
    restore?.focus()
  })
}
