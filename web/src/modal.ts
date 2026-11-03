import { onMounted, onUnmounted, type ShallowRef } from 'vue'

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

interface ModalLifetime {
  leaving: boolean
  restore: HTMLElement | null
  finish: () => void
}

const modals = new Map<Element, ModalLifetime>()
const fallbacks = new Set<Element>()
let previousOverflow = ''

/** Called by ModalTransition before a departing dialog starts to fade. */
export function startModalLeave(element: Element): void {
  const lifetime = modals.get(element)
  if (lifetime) lifetime.leaving = true
  // A retiring form must not accept another click while its state is gone.
  element.setAttribute('inert', '')
  // Older fallback browsers do not implement inert.
  element.addEventListener(
    'click',
    (event) => {
      event.preventDefault()
      event.stopImmediatePropagation()
    },
    true,
  )
}

/** Called after physical removal, when focus can return outside the top layer. */
export function finishModalLeave(element: Element): void {
  modals.get(element)?.finish()
}

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
  let element: HTMLDialogElement | null = null
  let native = false
  const lifetime: ModalLifetime = { leaving: false, restore: null, finish }

  function finish(): void {
    if (!element || !modals.delete(element)) return
    if (native) {
      if (element.open) element.close()
    } else {
      document.removeEventListener('keydown', onKeydown, true)
      fallbacks.delete(element)
      if (!fallbacks.size) document.body.style.overflow = previousOverflow
    }
    // A replacement may already be open. Never steal its focus, and keep the
    // original page opener rather than a button in the departing dialog.
    if (!modals.size) lifetime.restore?.focus()
  }

  /* No visibility filter: the selector already skips what is disabled, and a
     dialog here shows everything it holds. Asking whether an element is drawn
     means measuring it, which is a layout on every Tab. */
  function focusables(): HTMLElement[] {
    return [...(dialog.value?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])]
  }

  function onKeydown(event: KeyboardEvent): void {
    if ([...modals.values()].pop() !== lifetime) return
    if (lifetime.leaving) {
      event.preventDefault()
      return
    }
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
    element = dialog.value
    if (!element) return

    const previous = [...modals.values()].pop()
    lifetime.restore = previous
      ? previous.restore
      : document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    modals.set(element, lifetime)

    native = supportsModal()
    if (native) {
      element.showModal()
      return
    }

    element.setAttribute('open', '')
    element.setAttribute('data-modal-fallback', '')
    element.setAttribute('aria-modal', 'true')
    element.setAttribute('role', 'dialog')
    /* The page behind a modal must not scroll under it, which is the last of
       the things the top layer would have taken care of. */
    if (!fallbacks.size) previousOverflow = document.body.style.overflow
    fallbacks.add(element)
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKeydown, true)
  })

  onUnmounted(() => {
    // A direct unmount (including route changes and non-animated callers)
    // still cleans up. Transition hooks run before this queued lifecycle hook.
    if (!lifetime.leaving) finish()
  })
}
