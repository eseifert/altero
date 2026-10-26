import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'

import { i18n } from '@/i18n'
import { useToastStore } from '@/stores/toasts'

import Collapse from './Collapse.vue'
import ToastHost from './ToastHost.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en-US'
})

describe('ToastHost', () => {
  function host() {
    return mount(ToastHost, { global: { plugins: [i18n] } })
  }

  it('is a live region before it has anything to say', () => {
    /* A region that appears with its first message is one some screen
       readers never announce. */
    const region = host().get('.toasts')

    expect(region.attributes('role')).toBe('status')
    expect(region.attributes('aria-live')).toBe('polite')
  })

  it('shows a message with what it offers', async () => {
    const wrapper = host()
    const run = vi.fn()
    useToastStore().show('Moved to the trash', { label: 'Undo', run })
    await nextTick()

    expect(wrapper.text()).toContain('Moved to the trash')
    await wrapper.get('.toast__action').trigger('click')

    expect(run).toHaveBeenCalledOnce()
  })

  it('can be dismissed, by a button that says so', async () => {
    const wrapper = host()
    useToastStore().show('Moved to the trash')
    await nextTick()

    const dismiss = wrapper.get('.toast__dismiss')
    expect(dismiss.attributes('aria-label')).toBe('Dismiss')
    await dismiss.trigger('click')

    expect(useToastStore().toasts).toHaveLength(0)
  })

  it('holds a toast while the pointer is on it', async () => {
    const wrapper = host()
    const store = useToastStore()
    const hold = vi.spyOn(store, 'hold')
    store.show('Moved to the trash')
    await nextTick()

    await wrapper.get('.toast').trigger('pointerenter')

    expect(hold).toHaveBeenCalled()
  })
})

describe('Collapse', () => {
  it('shows and hides what it wraps', async () => {
    const open = ref(true)
    const wrapper = mount(
      defineComponent(() => () => h(Collapse, null, () => (open.value ? h('p', 'Inside') : null))),
    )
    expect(wrapper.text()).toBe('Inside')

    open.value = false
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(wrapper.text()).toBe('')
  })
})
