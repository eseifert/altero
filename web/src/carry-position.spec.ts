import { afterEach, expect, it, vi } from 'vitest'

import { useCarry } from './dragging'

afterEach(() => {
  document.documentElement.dir = 'ltr'
  vi.restoreAllMocks()
})

it.each([['ltr', 'translate(240px, 180px)'], ['rtl', 'translate(-760px, 180px)']] as const)(
  'keeps %s drag previews by the pointer with a logical start anchor', (direction, expected) => {
    document.documentElement.dir = direction
    vi.spyOn(document.documentElement, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 1000, 768))
    // A reserved scrollbar gutter need not be reflected in clientWidth.
    vi.spyOn(document.documentElement, 'clientWidth', 'get').mockReturnValue(1024)
    const carry = useCarry<string>()
    carry.position.value = { x: 240, y: 180 }

    expect(carry.transform.value).toBe(expected)
    // Hit testing still needs the physical viewport coordinates.
    expect(carry.position.value).toEqual({ x: 240, y: 180 })
  },
)
