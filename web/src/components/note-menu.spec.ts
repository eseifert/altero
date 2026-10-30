import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'

import NoteMenu, { type NoteMenuEntry } from './NoteMenu.vue'

afterEach(() => vi.restoreAllMocks())

const CASES: { entries: NoteMenuEntry[] }[] = [
  { entries: [{ id: 'new', label: 'New Standalone Note', kind: 'action' }] },
  { entries: [
    { id: 'first', label: 'First format', kind: 'radio', checked: false },
    { id: 'selected', label: 'Selected format', kind: 'radio', checked: true },
  ] },
]

it.each(CASES)('positions the menu before focusing an entry: %j', async ({ entries }) => {
  vi.spyOn(HTMLButtonElement.prototype, 'getBoundingClientRect')
    .mockReturnValue(new DOMRect(20, window.innerHeight - 40, 48, 40))
  const focus = HTMLElement.prototype.focus
  let positionAtFocus: string | undefined
  let preventedScroll: boolean | undefined
  vi.spyOn(HTMLElement.prototype, 'focus').mockImplementation(function (this: HTMLElement, options?: FocusOptions) {
    if (this.matches('[role^="menuitem"]')) {
      positionAtFocus = (this.closest('[role="menu"]') as HTMLElement).style.bottom
      preventedScroll = options?.preventScroll
    }
    focus.call(this, options)
  })
  const wrapper = mount(NoteMenu, {
    props: { label: 'New Note', icon: 'new-note', entries }, attachTo: document.body,
  })
  try {
    await wrapper.get('[aria-haspopup]').trigger('click')
    await flushPromises()

    // Focusing a fixed menu before its viewport position is applied can scroll
    // the document, whose scroll handler then dismisses the menu.
    expect(positionAtFocus).toBe('44px')
    expect(preventedScroll).toBe(true)
    expect(wrapper.get('[role="menu"]').isVisible()).toBe(true)
    const expected = entries.find(entry => entry.checked) ?? entries[0]!
    expect(document.activeElement?.textContent?.trim()).toBe(expected.label)
  } finally { wrapper.unmount() }
})

it('scrolls a long menu to the focused option without scrolling its ancestors', async () => {
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(80)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(32)
  vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockImplementation(function (this: HTMLElement) {
    return this.textContent?.trim() === 'Selected format' ? 160 : 0
  })
  const wrapper = mount(NoteMenu, { props: { label: 'Format', icon: 'format-text', entries: CASES[1]!.entries }, attachTo: document.body })
  try {
    await wrapper.get('[aria-haspopup]').trigger('click')
    await flushPromises()
    const menu = wrapper.get('[role="menu"]')
    expect(menu.element.scrollTop).toBe(112)
    expect(document.activeElement?.textContent?.trim()).toBe('Selected format')

    await menu.trigger('keydown', { key: 'Home' })
    expect(menu.element.scrollTop).toBe(0)
    expect(document.activeElement?.textContent?.trim()).toBe('First format')
    await menu.trigger('keydown', { key: 'End' })
    expect(menu.element.scrollTop).toBe(112)
    expect(document.activeElement?.textContent?.trim()).toBe('Selected format')
  } finally { wrapper.unmount() }
})

it('ignores a queued scroll at the opening position but dismisses a moved anchor', async () => {
  const bounds = vi.spyOn(HTMLButtonElement.prototype, 'getBoundingClientRect')
    .mockReturnValue(new DOMRect(20, 500, 48, 40))
  const wrapper = mount(NoteMenu, { props: { label: 'New Note', icon: 'new-note', entries: CASES[0]!.entries }, attachTo: document.body })
  try {
    await wrapper.get('[aria-haspopup]').trigger('click')
    await flushPromises()
    document.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[role="menu"]').exists()).toBe(true)

    bounds.mockReturnValue(new DOMRect(20, 480, 48, 40))
    wrapper.get('[role="menu"]').element.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[role="menu"]').exists()).toBe(true)
    document.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  } finally { wrapper.unmount() }
})
