import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref, vShow, withDirectives } from 'vue'

import { i18n } from '@/i18n'
import { useToastStore } from '@/stores/toasts'

import Collapse from './Collapse.vue'
import ToastHost from './ToastHost.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en-US'
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
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

  it('keeps its focus hold when tabbing between action and dismiss', async () => {
    const wrapper = host()
    const store = useToastStore()
    const release = vi.spyOn(store, 'release')
    const id = store.show('Moved to the trash', { label: 'Undo', run: vi.fn() })
    await nextTick()
    await wrapper.get('.toast').trigger('focusout', {
      relatedTarget: wrapper.get('.toast__dismiss').element,
    })
    expect(release).not.toHaveBeenCalled()
    await wrapper.get('.toast').trigger('focusout', { relatedTarget: null })
    expect(release).toHaveBeenCalledWith(id, 'focus')
  })
})

describe('Collapse', () => {
  it('leaves intrinsic-size animation to CSS without measuring the section', async () => {
    vi.stubGlobal('CSS', { supports: (property: string, value: string) =>
      property === 'interpolate-size' && value === 'allow-keywords',
    })
    const open = ref(false)
    const wrapper = mount(defineComponent(() => () => h(Collapse, null, () =>
      withDirectives(h('section', [h('button', 'Write')]), [[vShow, open.value]]),
    )), { global: { stubs: { transition: false } } })
    const section = wrapper.get('section').element
    const contentHeight = vi.spyOn(section, 'scrollHeight', 'get').mockReturnValue(84)
    const rect = vi.spyOn(section, 'getBoundingClientRect')
    open.value = true
    await nextTick()
    expect(contentHeight).not.toHaveBeenCalled()
    expect(section.style.height).toBe('')
    open.value = false
    await nextTick()
    expect(rect).not.toHaveBeenCalled()
    expect(section.hasAttribute('inert')).toBe(true)
  })

  it('measures the opening height when intrinsic interpolation is unavailable', async () => {
    vi.stubGlobal('CSS', { supports: () => false })
    const open = ref(false)
    const wrapper = mount(defineComponent(() => () => h(Collapse, null, () =>
      withDirectives(h('section', 'Content'), [[vShow, open.value]]),
    )), { global: { stubs: { transition: false } } })
    const section = wrapper.get('section').element
    vi.spyOn(section, 'scrollHeight', 'get').mockReturnValue(84)
    open.value = true
    await nextTick()
    expect(section.style.height).toBe('84px')
  })

  it('retires controls immediately while their content is leaving', async () => {
    const open = ref(true)
    const clicked = vi.fn()
    const wrapper = mount(defineComponent(() => () => h(Collapse, null, () =>
      open.value ? h('section', [h('button', { onClick: clicked }, 'Write')]) : null,
    )), { global: { stubs: { transition: false } } })
    const section = wrapper.get('section').element
    const button = wrapper.get('button').element
    open.value = false
    await nextTick()
    expect(section.hasAttribute('inert')).toBe(true)
    expect(section.getAttribute('aria-hidden')).toBe('true')
    // jsdom, like older Safari, does not implement inert's behavior.
    button.click()
    expect(clicked).not.toHaveBeenCalled()
  })

  it('revives controls and releases the height after cancelling a close', async () => {
    const open = ref(true)
    const clicked = vi.fn()
    const wrapper = mount(defineComponent(() => () => h(Collapse, null, () =>
      withDirectives(h('section', [h('button', { onClick: clicked }, 'Write')]), [[vShow, open.value]]),
    )), { global: { stubs: { transition: false } } })
    const section = wrapper.get('section').element
    open.value = false
    await nextTick()
    expect(section.hasAttribute('inert')).toBe(true)
    open.value = true
    await nextTick()
    await vi.waitFor(() => expect(section.style.height).toBe(''))
    expect(section.hasAttribute('inert')).toBe(false)
    expect(section.hasAttribute('aria-hidden')).toBe(false)
    wrapper.get('button').element.click()
    expect(clicked).toHaveBeenCalledOnce()
  })

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
