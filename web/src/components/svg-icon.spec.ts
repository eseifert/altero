import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { CONTROL_ICONS, loadIcons } from '@/icons'
import { ITEM_TYPE_ICONS } from '@/items/icons'
import { SIDEBAR_ICONS } from '@/items/sidebaricons'
import SvgIcon from './SvgIcon.vue'

describe('SVG file rendering', () => {
  it('renders every bundled icon with its file attributes and a label when requested', () => {
    for (const icon of Object.values({ ...ITEM_TYPE_ICONS, ...SIDEBAR_ICONS, ...CONTROL_ICONS })) {
      const wrapper = mount(SvgIcon, { props: { icon, size: 12, labelled: true } })
      expect(wrapper.attributes('viewBox')).toBe('0 0 24 24')
      expect(wrapper.attributes('stroke')).toBe('currentColor')
      expect(wrapper.attributes('width')).toBe('12')
      expect(wrapper.attributes('height')).toBe('12')
      expect(wrapper.attributes('aria-label')).toBeTruthy()
      expect(wrapper.get('title').text()).toBe(icon.label)
      expect(wrapper.find('path, circle, rect, polygon, polyline, ellipse, line').exists()).toBe(true)
      wrapper.unmount()
    }
  })

  it('preserves hand-edited shapes, groups and presentation attributes', async () => {
    const icons = loadIcons({
      'custom.svg': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="currentColor" stroke-width="3"><title>Custom</title><g transform="translate(2 3)"><circle cx="8" cy="9" r="4"/><rect x="16" y="4" width="6" height="8"/></g></svg>',
    })
    const wrapper = mount(SvgIcon, { props: { icon: CONTROL_ICONS.edit } })
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.find('title').exists()).toBe(false)

    await wrapper.setProps({ icon: icons.custom, labelled: true })

    expect(wrapper.attributes('viewBox')).toBe('0 0 32 32')
    expect(wrapper.attributes('fill')).toBe('currentColor')
    expect(wrapper.attributes('stroke-width')).toBe('3')
    expect(wrapper.get('g[transform]').attributes('transform')).toBe('translate(2 3)')
    expect(wrapper.get('circle').attributes('r')).toBe('4')
    expect(wrapper.get('rect').attributes('width')).toBe('6')
    expect(wrapper.find('path').exists()).toBe(false)
    expect(wrapper.attributes('aria-hidden')).toBeUndefined()
    expect(wrapper.attributes('aria-label')).toBe('Custom')
  })

  it('reports a broken SVG file rather than silently rendering an empty icon', () => {
    expect(() => loadIcons({ 'broken.svg': '<svg><path></svg>' })).toThrow('broken.svg')
  })
})
