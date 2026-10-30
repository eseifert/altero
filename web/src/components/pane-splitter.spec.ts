import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import PaneSplitter from './PaneSplitter.vue'

afterEach(() => { document.documentElement.dir = 'ltr' })

describe.each([
  ['ltr', false, 340, 316, 284, 100, 600],
  ['ltr', true, 260, 284, 316, 600, 100],
  ['rtl', false, 260, 284, 316, 600, 100],
  ['rtl', true, 340, 316, 284, 100, 600],
] as const)('%s splitter, trailing=%s', (direction, trailing, dragged, right, left, home, end) => {
  function open() {
    document.documentElement.dir = direction
    return mount(PaneSplitter, {
      props: { width: 300, min: 100, max: 600, preferred: 320, label: 'Pane width', trailing },
    })
  }

  it('follows physical pointer movement on the correct side', () => {
    const wrapper = open()
    try {
      wrapper.element.dispatchEvent(new MouseEvent('pointerdown', { clientX: 200, bubbles: true }))
      window.dispatchEvent(new MouseEvent('pointermove', { clientX: 240 }))
      window.dispatchEvent(new MouseEvent('pointerup'))

      expect(wrapper.emitted('update:width')?.at(-1)).toEqual([dragged])
    } finally { wrapper.unmount() }
  })

  it('keeps arrows and Home/End tied to the physical divider position', async () => {
    const wrapper = open()
    try {
      for (const [key, expected] of [
        ['ArrowRight', right], ['ArrowLeft', left], ['Home', home], ['End', end],
      ] as const) {
        await wrapper.trigger('keydown', { key })
        expect(wrapper.emitted('update:width')?.at(-1), key).toEqual([expected])
      }
    } finally { wrapper.unmount() }
  })
})
