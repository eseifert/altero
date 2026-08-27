import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useThemeStore } from '@/stores/theme'

import ThemeMenu from './ThemeMenu.vue'

/** Mount attached to the document, so focus and outside clicks behave. */
function open() {
  return mount(ThemeMenu, { attachTo: document.body })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.body.innerHTML = ''
})

describe('ThemeMenu', () => {
  it('is one control until it is asked for more', () => {
    const wrapper = open()

    expect(wrapper.findAll('button')).toHaveLength(1)
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  })

  it('says which theme is set, for anyone who cannot see the glyph', () => {
    const wrapper = open()

    expect(wrapper.get('.theme-menu__trigger').attributes('aria-label')).toBe(
      'Color theme: System',
    )
  })

  it('opens the options on a click', async () => {
    const wrapper = open()

    await wrapper.get('.theme-menu__trigger').trigger('click')

    expect(wrapper.get('[role="menu"]').isVisible()).toBe(true)
    expect(wrapper.findAll('[role="menuitemradio"]')).toHaveLength(3)
    expect(wrapper.get('.theme-menu__trigger').attributes('aria-expanded')).toBe('true')
  })

  it('marks the option in force rather than only colouring it', async () => {
    const wrapper = open()
    useThemeStore().setPreference('dark')

    await wrapper.get('.theme-menu__trigger').trigger('click')

    const checked = wrapper
      .findAll('[role="menuitemradio"]')
      .filter((item) => item.attributes('aria-checked') === 'true')
    expect(checked).toHaveLength(1)
    expect(checked[0].text()).toContain('Dark')
  })

  it('applies a choice and closes', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')

    await wrapper.findAll('[role="menuitemradio"]')[1].trigger('click')

    expect(useThemeStore().preference).toBe('dark')
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  })

  it('shows the chosen setting on the trigger afterwards', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')

    await wrapper.findAll('[role="menuitemradio"]')[0].trigger('click')

    expect(wrapper.get('.theme-menu__trigger').attributes('aria-label')).toBe('Color theme: Light')
  })

  it('closes on Escape without changing anything', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(useThemeStore().preference).toBe('system')
  })

  it('closes when something else is clicked', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')

    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  })

  it('stays open when the click is inside it', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')

    wrapper.get('[role="menu"]').element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[role="menu"]').exists()).toBe(true)
  })

  it('puts focus on the option in force, so the keyboard can take over', async () => {
    const wrapper = open()
    useThemeStore().setPreference('dark')

    await wrapper.get('.theme-menu__trigger').trigger('click')
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(wrapper.findAll('[role="menuitemradio"]')[1].element)
  })

  it('moves between the options with the arrow keys, wrapping round', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')
    await wrapper.vm.$nextTick()

    const options = wrapper.findAll('[role="menuitemradio"]')
    await options[2].trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(options[0].element)

    await options[0].trigger('keydown', { key: 'ArrowUp' })
    expect(document.activeElement).toBe(options[2].element)
  })

  it('gives focus back to the trigger when it closes', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(wrapper.get('.theme-menu__trigger').element)
  })

  it('stops listening to the document once it is gone', async () => {
    const wrapper = open()
    await wrapper.get('.theme-menu__trigger').trigger('click')

    wrapper.unmount()

    // Would throw on a released component if the handlers were still attached.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
  })
})
