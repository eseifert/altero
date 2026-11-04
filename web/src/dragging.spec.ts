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

function gesture(onDrop = vi.fn(() => Promise.resolve(true))) {
  const scope = effectScope()
  const carry = scope.run(() => useCarry<string>())!
  source.onpointerdown = (event) => carry.begin(event, { label: 'Book', data: 'book' }, {
    accepts: () => true, onDrop,
  })
  pointer('pointerdown', { clientX: 10, clientY: 10 })
  pointer('pointermove')
  return { carry, scope, onDrop }
}

beforeEach(() => {
  vi.useFakeTimers()
  document.elementFromPoint = vi.fn(() => destination)
})

afterEach(() => {
  pointer('pointercancel')
  source.onpointerdown = null
  vi.useRealTimers()
  vi.restoreAllMocks()
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
