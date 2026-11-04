import { effectScope } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'

import { useTouchPress } from './touchpress'

const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop())
  document.body.innerHTML = ''
  Reflect.deleteProperty(document, 'elementFromPoint')
})

function setup() {
  const scope = effectScope()
  scopes.push(scope)
  scope.run(useTouchPress)
  // jsdom has no hit testing; the browser checks exercise actual coordinates.
  Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn() })
  document.body.innerHTML = '<button class="icon-button"><svg></svg></button><button class="app-button" disabled>Save</button>'
  return { scope, button: document.querySelector('button')!, icon: document.querySelector('svg')! }
}

function pointer(target: EventTarget, type: string, overrides: PointerEventInit = {}) {
  const event = new PointerEvent(type, { bubbles: true, cancelable: true, pointerType: 'touch', pointerId: 7, isPrimary: true, button: 0, ...overrides })
  target.dispatchEvent(event)
  return event
}

it('shows a touch press on the containing button and releases it outside the button', () => {
  const { button, icon } = setup()
  expect(pointer(icon, 'pointerdown').defaultPrevented).toBe(false)
  expect(button.hasAttribute('data-touch-pressed')).toBe(true)
  pointer(window, 'pointerup', { pointerId: 8 })
  expect(button.hasAttribute('data-touch-pressed')).toBe(true)
  pointer(window, 'pointerup')
  expect(button.hasAttribute('data-touch-pressed')).toBe(false)
})

it.each(['pointercancel', 'lostpointercapture', 'blur', 'scroll'])('clears touch feedback on %s', (event) => {
  const { button, icon } = setup()
  pointer(icon, 'pointerdown')
  expect(button.hasAttribute('data-touch-pressed')).toBe(true)
  if (event.startsWith('pointer') || event === 'lostpointercapture') pointer(window, event)
  else window.dispatchEvent(new Event(event))
  expect(button.hasAttribute('data-touch-pressed')).toBe(false)
})

it('clears when the finger moves off the button, allowing native scrolling', () => {
  const { button, icon } = setup()
  vi.mocked(document.elementFromPoint).mockReturnValue(icon)
  pointer(icon, 'pointerdown')
  pointer(window, 'pointermove')
  expect(button.hasAttribute('data-touch-pressed')).toBe(true)
  vi.mocked(document.elementFromPoint).mockReturnValue(document.body)
  pointer(window, 'pointermove')
  expect(button.hasAttribute('data-touch-pressed')).toBe(false)
})

it('leaves mouse, secondary pointers, disabled buttons and ordinary content alone', () => {
  const { button, icon } = setup()
  pointer(icon, 'pointerdown', { pointerType: 'mouse' })
  expect(document.querySelector('[data-touch-pressed]')).toBeNull()
  pointer(icon, 'pointerdown', { isPrimary: false })
  expect(document.querySelector('[data-touch-pressed]')).toBeNull()
  pointer(icon, 'pointerdown', { button: 2 })
  expect(document.querySelector('[data-touch-pressed]')).toBeNull()
  pointer(document.querySelector('button:disabled')!, 'pointerdown')
  expect(document.querySelector('[data-touch-pressed]')).toBeNull()
  pointer(document.body, 'pointerdown')
  expect(document.querySelector('[data-touch-pressed]')).toBeNull()
  expect(button.disabled).toBe(false)
})

it('removes feedback and listeners when its scope ends', () => {
  const { scope, button, icon } = setup()
  pointer(icon, 'pointerdown')
  expect(button.hasAttribute('data-touch-pressed')).toBe(true)
  scope.stop()
  expect(button.hasAttribute('data-touch-pressed')).toBe(false)
  pointer(icon, 'pointerdown')
  expect(button.hasAttribute('data-touch-pressed')).toBe(false)
})

it('keeps feedback while a form field loses focus inside the page', () => {
  const { button, icon } = setup()
  const field = document.createElement('input')
  document.body.append(field)
  pointer(icon, 'pointerdown')
  field.dispatchEvent(new FocusEvent('blur'))
  expect(button.hasAttribute('data-touch-pressed')).toBe(true)
})
