import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ItemEnvelope } from '@/stores/library'
import DuplicateGroups from './DuplicateGroups.vue'

const row = (key: string): ItemEnvelope => ({ key, version: 1, data: { itemType: 'book', title: key }, meta: {} })
const items = ['OLD', 'NEW', 'OTHER', 'LAST'].map(row)
const props = { items, groups: [['OLD', 'NEW'], ['OTHER', 'LAST']], selection: ['OLD', 'NEW'], tabKey: 'OLD' }

describe('the grouped duplicate overview', () => {
  it('shows separate groups with the proposed master at the top and highlights every selected member', () => {
    const wrapper = mount(DuplicateGroups, { props })
    expect(wrapper.findAll('.duplicate-group')).toHaveLength(2)
    expect(wrapper.findAll('.duplicate-group')[0]!.findAll('[data-row]').map((row) => row.attributes('data-row'))).toEqual(['OLD', 'NEW'])
    expect(wrapper.findAll('.row--current')).toHaveLength(2)
    expect(wrapper.findAll('.duplicate-group__master')).toHaveLength(2)
  })

  it('activates a group with an ordinary tap on any member', async () => {
    const wrapper = mount(DuplicateGroups, { props })
    await wrapper.get('[data-row="NEW"]').trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toEqual(items[1])
  })

  it('moves an explicitly chosen master to the top of its group', () => {
    const wrapper = mount(DuplicateGroups, { props: { ...props, master: 'NEW' } })
    expect(wrapper.findAll('.duplicate-group')[0]!.findAll('[data-row]').map((row) => row.attributes('data-row'))).toEqual(['NEW', 'OLD'])
  })
})
