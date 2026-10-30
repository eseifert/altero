import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppTextField from './AppTextField.vue'
import CollectionTree from './CollectionTree.vue'

describe('content direction independently of the interface', () => {
  it('lets typed text choose its own direction without changing the label', async () => {
    const wrapper = mount(AppTextField, { props: { label: 'Display name' } })
    await wrapper.get('input').setValue('فارسی 123')
    expect(wrapper.get('input').attributes('dir')).toBe('auto')
    expect(wrapper.get('label').attributes('dir')).toBeUndefined()
  })

  it('isolates collection names from their icons and item counts', () => {
    const wrapper = mount(CollectionTree, { props: {
      nodes: [{ key: 'ABCD2345', version: 1, data: { key: 'ABCD2345', name: 'שלום (2026)', parentCollection: false }, meta: { numCollections: 0, numItems: 12 }, children: [] }],
      selected: null,
    } })
    expect(wrapper.get('.tree__label').attributes('dir')).toBe('auto')
    expect(wrapper.get('.tree__name').attributes('dir')).toBeUndefined()
    expect(wrapper.get('.tree__count').text()).toBe('12')
  })
})
