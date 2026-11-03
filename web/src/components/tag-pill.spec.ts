import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import TagPill from './TagPill.vue'

afterEach(() => { document.body.innerHTML = '' })

function pill(props: { filterable?: boolean; rename?: (name: string) => Promise<unknown>; numItems?: number } = {}) {
  return mount(TagPill, { props: { name: 'whales', ...props }, attachTo: document.body })
}

describe('a shared tag pill', () => {
  it('does not save when replacing the focused pencil with its field', async () => {
    const rename = vi.fn()
    const wrapper = pill({ rename })
    const opened = wrapper.get('.tag-pill__edit').trigger('click')
    // Removing the focused pencil can emit focusout before the field takes focus.
    await wrapper.get('li').trigger('focusout', { relatedTarget: null })
    await opened
    expect(wrapper.find('input').exists()).toBe(true)
    expect(rename).not.toHaveBeenCalled()
  })

  it('filters only when its caller enables name clicks', async () => {
    const global = pill({ filterable: true })
    await global.get('.tag-pill__name').trigger('click')
    expect(global.emitted('filter')).toEqual([[]])
    const local = pill()
    expect(local.get('.tag-pill__name').element.tagName).toBe('SPAN')
    await local.get('.tag-pill__name').trigger('click')
    expect(local.emitted('filter')).toBeUndefined()
  })

  it('selects the existing name from the pencil and saves once on Enter', async () => {
    let finish!: () => void
    const rename = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    const wrapper = pill({ rename })
    await wrapper.get('.tag-pill__edit').trigger('click')
    const field = wrapper.get('input')
    expect(field.element).toBe(document.activeElement)
    expect((field.element as HTMLInputElement).selectionStart).toBe(0)
    expect((field.element as HTMLInputElement).selectionEnd).toBe(6)
    await field.setValue(' dolphins ')
    await field.trigger('keydown', { key: 'Enter' })
    await field.trigger('keydown', { key: 'Enter' })
    expect(rename).toHaveBeenCalledExactlyOnceWith('dolphins')
    expect(field.attributes('disabled')).toBeDefined()
    finish()
    await flushPromises()
    expect(wrapper.find('input, dialog').exists()).toBe(false)
  })

  it('saves when focus leaves the pill', async () => {
    const rename = vi.fn().mockResolvedValue(undefined)
    const wrapper = pill({ rename })
    await wrapper.get('.tag-pill__edit').trigger('click')
    await wrapper.get('input').setValue('dolphins')
    await wrapper.get('li').trigger('focusout', { relatedTarget: null })
    await flushPromises()
    expect(rename).toHaveBeenCalledExactlyOnceWith('dolphins')
  })

  it('does not save when moving to the cancel control or canceling', async () => {
    const rename = vi.fn()
    const wrapper = pill({ rename })
    await wrapper.get('.tag-pill__edit').trigger('click')
    await wrapper.get('input').setValue('dolphins')
    const cancel = wrapper.get('[aria-label="Cancel"]')
    await wrapper.get('li').trigger('focusout', { relatedTarget: cancel.element })
    await cancel.trigger('click')
    await flushPromises()
    expect(rename).not.toHaveBeenCalled()
    expect(wrapper.get('.tag-pill__name').text()).toBe('whales')
    expect(wrapper.get('.tag-pill__edit').element).toBe(document.activeElement)
  })

  it('makes an unchanged name a no-op', async () => {
    const rename = vi.fn()
    const wrapper = pill({ rename })
    await wrapper.get('.tag-pill__edit').trigger('click')
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(rename).not.toHaveBeenCalled()
    expect(wrapper.find('input').exists()).toBe(false)
  })

  it('keeps the item count between the name and action, without a rename notice', async () => {
    const wrapper = pill({ rename: vi.fn(), numItems: 2 })
    expect(wrapper.get('.tag-pill__count').text()).toBe('2')
    expect(wrapper.get('.tag-pill__count').attributes('aria-label')).toBe('2 items')
    expect(wrapper.get('li').element.children[1]?.classList.contains('tag-pill__count')).toBe(true)
    expect(wrapper.get('li').element.children[2]?.className).toContain('tag-pill__edit')
    await wrapper.get('.tag-pill__edit').trigger('click')
    expect(wrapper.get('.tag-pill__count').text()).toBe('2')
    expect(wrapper.find('.tag-pill__hint').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('all associated items')
    expect(wrapper.get('input').attributes('aria-describedby')).toBeUndefined()
  })

  it('shows a zero count in a read-only global pill and no count on item tags', () => {
    expect(pill({ numItems: 0 }).get('.tag-pill__count').text()).toBe('0')
    expect(pill().find('.tag-pill__count').exists()).toBe(false)
  })
})
