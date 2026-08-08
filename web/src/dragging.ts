import { ref, type Ref } from 'vue'

/**
 * Carrying something from one row to another, with a pointer or a finger.
 *
 * Not the browser's own drag and drop. That API is a mouse API: a touch never
 * produces `dragstart`, so every phone and tablet would have been left with a
 * feature it could see the effects of and never use. Pointer events are one
 * code path for both, at the cost of doing the parts the browser used to do —
 * deciding when a press becomes a drag, finding what is underneath, and
 * drawing what is being carried.
 *
 * The two gestures differ in exactly one place, and they have to. A mouse
 * starts carrying as soon as it has moved a few pixels with the button down,
 * because a mouse has nothing else it could be doing. A finger that moves is
 * usually scrolling, so a touch starts carrying only after it has stayed put
 * for a moment — and moving before that cancels the carry and leaves the
 * scroll alone.
 */

/** What is being carried: a label to draw, and whatever the view needs back. */
export interface Carried<T = unknown> {
  label: string
  data: T
}

/** How far a mouse moves before a press is a drag rather than a click. */
const THRESHOLD = 5

/** How long a finger stays put before a press is a drag rather than a tap. */
const HOLD = 350

/** How close to the edge of the window a carry starts scrolling it. */
const EDGE = 72

/** How fast it scrolls there, in pixels per frame. */
const SPEED = 12

/**
 * What is under the pointer, as the row it belongs to named itself.
 *
 * Rows say what they are with `data-drop`, so this stays a lookup rather than
 * a register of rectangles that would have to be kept up to date as the tree
 * expands, the list pages and the window resizes.
 */
function dropAt(x: number, y: number): string | null {
  const element = document.elementFromPoint(x, y)
  return element?.closest('[data-drop]')?.getAttribute('data-drop') ?? null
}

export interface Carry<T> {
  /** What is being carried, or null while nothing is. */
  carrying: Ref<Carried<T> | null>
  /** The row underneath it, as `data-drop` names it. */
  target: Ref<string | null>
  /** Where to draw what is being carried. */
  position: Ref<{ x: number; y: number }>
  /** Begin a possible carry from a press. */
  begin: (event: PointerEvent, carried: Carried<T>, drop: Drop) => void
  /** Give up on the carry in progress, if there is one. */
  cancel: () => void
}

interface Drop {
  /** Whether ``target`` will take what is being carried. Undecided rows do not light up. */
  accepts: (target: string) => boolean
  /** Do it. ``modified`` is the Shift a mouse can hold and a finger cannot. */
  onDrop: (target: string, options: { modified: boolean }) => void
}

export function useCarry<T>(): Carry<T> {
  const carrying = ref<Carried<T> | null>(null) as Ref<Carried<T> | null>
  const target = ref<string | null>(null)
  const position = ref({ x: 0, y: 0 })

  let stop: (() => void) | null = null

  function cancel(): void {
    stop?.()
  }

  function begin(event: PointerEvent, carried: Carried<T>, drop: Drop): void {
    // A right or middle button is a menu or a paste, not a drag.
    if (event.button !== 0) return
    cancel()

    /* The row the press landed on. The click that follows a carry is
       dispatched here, and here is where it is caught: a listener on the
       window would have to sit in the path of every click in the page to
       catch one. */
    const source = event.currentTarget as EventTarget | null
    const originX = event.clientX
    const originY = event.clientY
    /* A finger or a stylus waits; everything else -- a mouse, a trackpad, and
       anything that did not say what it was -- starts on movement. */
    const touch = event.pointerType === 'touch' || event.pointerType === 'pen'
    let active = false
    let hold: ReturnType<typeof setTimeout> | undefined
    let scrolling: number | undefined

    /* A finger that has begun a carry must not also scroll the page. The
       gesture is only cancellable because the press stayed still long enough
       for the browser not to have started scrolling already, which is the same
       reason the carry waits. */
    const block = (blocked: Event) => blocked.preventDefault()

    /*
     * Scroll the window when the carry nears its edge.
     *
     * Without this a tree taller than the window can only be dropped into as
     * far as it is visible, which on a phone is about four rows.
     */
    const nudge = () => {
      const { y } = position.value
      const above = y < EDGE
      const below = y > window.innerHeight - EDGE
      if (active && (above || below)) window.scrollBy(0, above ? -SPEED : SPEED)
      scrolling = requestAnimationFrame(nudge)
    }

    const start = () => {
      active = true
      carrying.value = carried
      if (touch) document.addEventListener('touchmove', block, { passive: false })
      scrolling = requestAnimationFrame(nudge)
    }

    const move = (moved: PointerEvent) => {
      const far = Math.abs(moved.clientX - originX) + Math.abs(moved.clientY - originY) > THRESHOLD

      if (!active) {
        // Before the carry begins, movement means one of two things: a mouse
        // has decided to drag, and a finger has decided to scroll.
        if (touch) {
          if (far) finish()
          return
        }
        if (!far) return
        start()
      }

      position.value = { x: moved.clientX, y: moved.clientY }
      const under = dropAt(moved.clientX, moved.clientY)
      target.value = under && drop.accepts(under) ? under : null
    }

    const up = (released: PointerEvent) => {
      const landing = target.value
      const modified = released.shiftKey
      const carried = active
      finish()
      /* A carry ends on the row it began on as far as the browser is
         concerned, so a click follows it. Selecting an item because it was
         dragged somewhere is not what anybody meant, so the one click that
         comes out of a carry is swallowed. */
      if (carried && source) {
        source.addEventListener('click', swallow, { capture: true, once: true })
        // In case no click follows -- a carry released over another window,
        // say -- the listener must not outlive the gesture.
        setTimeout(() => source.removeEventListener('click', swallow, { capture: true }), 0)
      }
      if (landing) drop.onDrop(landing, { modified })
    }

    const swallow = (click: Event) => {
      click.preventDefault()
      click.stopPropagation()
    }

    function finish(): void {
      clearTimeout(hold)
      if (scrolling !== undefined) cancelAnimationFrame(scrolling)
      document.removeEventListener('touchmove', block)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', cancelled)
      active = false
      carrying.value = null
      target.value = null
      stop = null
    }

    const cancelled = () => finish()

    stop = () => finish()
    position.value = { x: originX, y: originY }
    if (touch) hold = setTimeout(start, HOLD)

    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', cancelled)
  }

  return { carrying, target, position, begin, cancel }
}
