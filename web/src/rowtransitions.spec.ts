import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { useRowTransitions } from './rowtransitions'

afterEach(() => document.body.replaceChildren())

function list(keys: string[]) {
  const list = document.createElement('ul')
  const rows = keys.map((key) => {
    const row = document.createElement('li')
    const button = document.createElement('button')
    button.dataset.row = key
    row.append(button)
    list.append(row)
    return { row, button }
  })
  document.body.append(list)
  return { list, rows }
}

describe('departing item rows', () => {
  it('moves focus to the next row, or the previous one at the end', async () => {
    const { rows: [first, middle, last] } = list(['FIRST', 'MIDDLE', 'LAST'])
    const motion = useRowTransitions(vi.fn())
    middle!.button.focus()
    motion.beforeLeave(middle!.row)
    middle!.row.remove()
    await nextTick()
    expect(document.activeElement).toBe(last!.button)
    motion.afterLeave(middle!.row)
    motion.beforeLeave(last!.row)
    last!.row.remove()
    await nextTick()
    expect(document.activeElement).toBe(first!.button)
    motion.afterLeave(last!.row)
    expect(motion.leaving.value).toBe(0)
  })

  it('moves focus to the view heading when its final row leaves', async () => {
    const { rows: [only] } = list(['ONLY'])
    const heading = document.createElement('h1')
    heading.tabIndex = -1
    document.body.append(heading)
    const motion = useRowTransitions(() => heading.focus())
    only!.button.focus()
    motion.beforeLeave(only!.row)
    only!.row.remove()
    await nextTick()
    expect(document.activeElement).toBe(heading)
    motion.afterLeave(only!.row)
  })

  it('does not take focus from another control', async () => {
    const { rows: [first] } = list(['FIRST', 'LAST'])
    const input = document.createElement('input')
    document.body.append(input)
    const empty = vi.fn()
    const motion = useRowTransitions(empty)
    first!.button.focus()
    motion.beforeLeave(first!.row)
    first!.row.remove()
    input.focus()
    await nextTick()
    expect(document.activeElement).toBe(input)
    expect(empty).not.toHaveBeenCalled()
    motion.afterLeave(first!.row)
  })

  it('blocks retiring controls and restores their attributes after cancellation', () => {
    const { rows: [only] } = list(['ONLY'])
    const click = vi.fn()
    const carry = vi.fn()
    only!.button.addEventListener('click', click)
    only!.button.addEventListener('pointerdown', carry)
    only!.row.setAttribute('aria-hidden', 'false')
    const motion = useRowTransitions(vi.fn())
    motion.beforeLeave(only!.row)
    motion.beforeLeave(only!.row)
    expect(motion.leaving.value).toBe(1)
    only!.button.click()
    only!.button.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }))
    expect(click).not.toHaveBeenCalled()
    expect(carry).not.toHaveBeenCalled()
    motion.afterLeave(only!.row)
    motion.afterLeave(only!.row)
    expect(motion.leaving.value).toBe(0)
    expect(only!.row.hasAttribute('inert')).toBe(false)
    expect(only!.row.getAttribute('aria-hidden')).toBe('false')
    expect(only!.row.style.getPropertyValue('--leaving-row-height')).toBe('')
    only!.button.click()
    only!.button.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }))
    expect(click).toHaveBeenCalledOnce()
    expect(carry).toHaveBeenCalledOnce()
  })
})
