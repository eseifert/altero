/** Temporarily disable departing content, including browsers without inert. */
const previous = new WeakMap<Element, (string | null)[]>()

function ignore(event: Event): void {
  event.preventDefault()
  event.stopImmediatePropagation()
}

export function retire(element: Element): void {
  if (previous.has(element)) return
  previous.set(element, [element.getAttribute('inert'), element.getAttribute('aria-hidden')])
  element.setAttribute('inert', '')
  element.setAttribute('aria-hidden', 'true')
  for (const type of ['pointerdown', 'click', 'keydown']) element.addEventListener(type, ignore, true)
}

export function revive(element: Element): void {
  const attributes = previous.get(element)
  if (!attributes) return
  for (const [index, name] of ['inert', 'aria-hidden'].entries()) {
    if (attributes[index] === null) element.removeAttribute(name)
    else element.setAttribute(name, attributes[index]!)
  }
  for (const type of ['pointerdown', 'click', 'keydown']) element.removeEventListener(type, ignore, true)
  previous.delete(element)
}
