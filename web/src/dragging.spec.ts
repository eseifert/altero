import { effectScope } from 'vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { useCarry } from './dragging'

const source = document.createElement('button')
const destination = document.createElement('div')
destination.dataset.drop = 'collection:AAAA2345'

function pointer(type: string, options: PointerEventInit = {}) {
  const event = new PointerEvent(type, { button: 0, clientX: 200, clientY: 200, ...options })
  const receiver = type === 'pointerdown' ? source : window
  receiver.dispatchEvent(event)
}

function gesture(onDrop = vi.fn(() => Promise.resolve(true)), pointerType = 'mouse') {
  const scope = effectScope()
  const carry = scope.run(() => useCarry<string>())!
  source.onpointerdown = (event) => carry.begin(event, { label: 'Book', data: 'book' }, {
    accepts: () => true, onDrop,
  })
  pointer('pointerdown', { clientX: 10, clientY: 10, pointerType })
  if (pointerType === 'touch') vi.advanceTimersByTime(350)
  else pointer('pointermove')
  return { carry, scope, onDrop }
}

beforeEach(() => {
  vi.useFakeTimers()
  document.body.append(source, destination)
  document.elementFromPoint = vi.fn(() => destination)
})

afterEach(() => {
  pointer('pointercancel')
  source.onpointerdown = null
  source.remove()
  destination.remove()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it.each(['mouse', 'touch'])('swallows the %s drag click on either the source or destination, even when delayed', async (pointerType) => {
  for (const target of [source, destination]) {
    const { scope } = gesture(undefined, pointerType)
    try {
      pointer('pointerup')
      await vi.advanceTimersByTimeAsync(50)
      const click = new PointerEvent('click', { bubbles: true, cancelable: true, detail: 1 })
      expect(target.dispatchEvent(click)).toBe(false)
      // The drag consumes only its own click.
      expect(target.dispatchEvent(new PointerEvent('click', { bubbles: true, cancelable: true, detail: 1 }))).toBe(true)
    } finally {
      scope.stop()
    }
  }
})

it.each(['next press', 'keyboard', 'another pointer', 'unmount', 'expiry'])('leaves clicks working after a drag: %s', async (action) => {
  const { scope } = gesture()
  pointer('pointerup')
  if (action === 'next press') destination.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
  if (action === 'unmount') scope.stop()
  if (action === 'expiry') await vi.advanceTimersByTimeAsync(2000)
  const click = new PointerEvent('click', {
    bubbles: true, cancelable: true,
    detail: action === 'keyboard' ? 0 : 1,
    pointerId: action === 'another pointer' ? 99 : 0,
  })
  expect(source.dispatchEvent(click)).toBe(true)
  scope.stop()
})

it('confirms the destination only after the drop succeeds, then clears it', async () => {
  let complete!: (value: boolean) => void
  const result = new Promise<boolean>((resolve) => { complete = resolve })
  const { carry, scope } = gesture(vi.fn(() => result))
  pointer('pointerup')
  expect(carry.carrying.value).toBeNull()
  expect(carry.confirmed.value).toBeNull()
  complete(true)
  await Promise.resolve()
  expect(carry.confirmed.value).toBe('collection:AAAA2345')
  await vi.advanceTimersByTimeAsync(300)
  expect(carry.confirmed.value).toBeNull()
  scope.stop()
})

it.each([false, 'reject'] as const)('does not confirm an unsuccessful drop: %s', async (result) => {
  const { carry, scope } = gesture(vi.fn(() => result === 'reject'
    ? Promise.reject(new Error('Failed')) : Promise.resolve(result)))
  pointer('pointerup')
  await Promise.resolve()
  expect(carry.confirmed.value).toBeNull()
  scope.stop()
})

it.each(['cancel', 'unmount', 'another drag'] as const)('ignores late completion after %s', async (action) => {
  let complete!: (value: boolean) => void
  const result = new Promise<boolean>((resolve) => { complete = resolve })
  const { carry, scope } = gesture(vi.fn(() => result))
  pointer('pointerup')
  if (action === 'unmount') scope.stop()
  else if (action === 'cancel') carry.cancel()
  else pointer('pointerdown', { clientX: 10, clientY: 10 })
  complete(true)
  await Promise.resolve()
  expect(carry.confirmed.value).toBeNull()
  scope.stop()
})

it('checks the released position instead of confirming a stale hover target', async () => {
  const { carry, scope, onDrop } = gesture()
  document.elementFromPoint = () => null
  pointer('pointerup')
  await Promise.resolve()
  expect(onDrop).not.toHaveBeenCalled()
  expect(carry.confirmed.value).toBeNull()
  scope.stop()
})

it.each(['Escape', 'blur', 'unmount'] as const)('cleans up an active gesture on %s', (action) => {
  const { carry, scope, onDrop } = gesture()
  expect(carry.carrying.value).not.toBeNull()
  if (action === 'unmount') scope.stop()
  else if (action === 'blur') window.dispatchEvent(new Event('blur'))
  else window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(carry.carrying.value).toBeNull()
  pointer('pointerup')
  expect(onDrop).not.toHaveBeenCalled()
  scope.stop()
})
