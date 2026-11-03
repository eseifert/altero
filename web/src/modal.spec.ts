import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, ref } from 'vue'

import { finishModalLeave, startModalLeave, useModal } from './modal'

const Dialog = defineComponent({
  setup() {
    const dialog = ref<HTMLDialogElement | null>(null)
    useModal(dialog, () => {})
    return () => h('dialog', { ref: dialog }, [h('input')])
  },
})

const showModal = HTMLDialogElement.prototype.showModal
const mounted: Element[] = []

afterEach(() => {
  for (const element of mounted.splice(0)) finishModalLeave(element)
  HTMLDialogElement.prototype.showModal = showModal
  document.body.replaceChildren()
  document.body.style.overflow = ''
})

for (const native of [true, false]) {
  describe(`modal lifetime (${native ? 'native' : 'fallback'})`, () => {
    function open() {
      // @ts-expect-error -- older Safari has no native modal API.
      if (!native) delete HTMLDialogElement.prototype.showModal
      const wrapper = mount(Dialog, { attachTo: document.body })
      mounted.push(wrapper.get('dialog').element)
      return wrapper
    }

    function opener() {
      const button = document.createElement('button')
      document.body.append(button)
      button.focus()
      return button
    }

    it('cleans up a direct unmount and restores the page focus', () => {
      const button = opener()
      const wrapper = open()
      wrapper.get('input').element.focus()
      wrapper.unmount()
      expect(document.activeElement).toBe(button)
      expect(document.body.style.overflow).toBe('')
    })

    it('keeps modal cleanup until the leave transition finishes', () => {
      const button = opener()
      document.body.style.overflow = 'auto'
      const wrapper = open()
      const element = wrapper.get('dialog').element
      wrapper.get('input').element.focus()
      startModalLeave(element)
      wrapper.unmount()
      expect(document.activeElement).not.toBe(button)
      if (!native) expect(document.body.style.overflow).toBe('hidden')
      finishModalLeave(element)
      expect(document.activeElement).toBe(button)
      expect(document.body.style.overflow).toBe('auto')
    })

    it('keeps a replacement focused and returns to the original page opener afterward', () => {
      const button = opener()
      document.body.style.overflow = 'auto'
      const first = open()
      first.get('input').element.focus()
      const departing = first.get('dialog').element
      startModalLeave(departing)
      first.unmount()
      const second = open()
      const field = second.get('input').element
      field.focus()
      const typed = new KeyboardEvent('keydown', { key: 'x', bubbles: true, cancelable: true })
      document.dispatchEvent(typed)
      expect(typed.defaultPrevented).toBe(false)
      finishModalLeave(departing)
      expect(document.activeElement).toBe(field)
      if (!native) expect(document.body.style.overflow).toBe('hidden')
      second.unmount()
      expect(document.activeElement).toBe(button)
      expect(document.body.style.overflow).toBe('auto')
    })
  })
}
