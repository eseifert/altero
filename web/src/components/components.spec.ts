import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppButton from './AppButton.vue'
import AppTextField from './AppTextField.vue'

describe('AppButton', () => {
  it('renders its label in the case it was given', () => {
    const wrapper = mount(AppButton, { slots: { default: 'Sign in' } })

    expect(wrapper.text()).toBe('Sign in')
  })

  it('never uppercases the label', () => {
    /* The brief says no all-caps, and Material 3 agrees; Material 2 did not,
       so this is the kind of thing a copied stylesheet reintroduces. */
    const wrapper = mount(AppButton, { slots: { default: 'Create account' } })

    expect(wrapper.text()).not.toBe('CREATE ACCOUNT')
    expect(wrapper.attributes('style') ?? '').not.toContain('uppercase')
  })

  it('is filled by default, which is the primary call to action', () => {
    expect(mount(AppButton).classes()).toContain('app-button--filled')
  })

  it('takes another variant', () => {
    expect(mount(AppButton, { props: { variant: 'text' } }).classes()).toContain('app-button--text')
  })

  it('defaults to type=button so it cannot submit a form by accident', () => {
    expect(mount(AppButton).attributes('type')).toBe('button')
  })

  it('can be a submit button when asked', () => {
    expect(mount(AppButton, { props: { type: 'submit' } }).attributes('type')).toBe('submit')
  })

  it('is disabled while loading, so a form cannot be submitted twice', () => {
    const wrapper = mount(AppButton, { props: { loading: true } })

    expect(wrapper.attributes('disabled')).toBeDefined()
    expect(wrapper.attributes('aria-busy')).toBe('true')
  })

  it('emits a click when it is enabled', async () => {
    const wrapper = mount(AppButton)

    await wrapper.trigger('click')

    expect(wrapper.emitted('click')).toHaveLength(1)
  })
})

describe('AppTextField', () => {
  it('binds the label to the input, so clicking it focuses the field', () => {
    const wrapper = mount(AppTextField, { props: { label: 'Username' } })

    const id = wrapper.find('input').attributes('id')
    expect(id).toBeTruthy()
    expect(wrapper.find('label').attributes('for')).toBe(id)
  })

  it('gives two fields on one page different ids', () => {
    // Mounted inside one parent on purpose: useId() counts per application,
    // so two separate mount() calls would each start again at the same value
    // and the test would pass or fail for reasons unrelated to the component.
    const wrapper = mount({
      components: { AppTextField },
      template: '<form><AppTextField label="Username" /><AppTextField label="Password" /></form>',
    })

    const [first, second] = wrapper.findAll('input')
    expect(first.attributes('id')).toBeTruthy()
    expect(first.attributes('id')).not.toBe(second.attributes('id'))
  })

  it('updates its model as the user types', async () => {
    const wrapper = mount(AppTextField, { props: { label: 'Username', modelValue: '' } })

    await wrapper.find('input').setValue('ada')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['ada'])
  })

  it('passes the autocomplete hint through, so password managers work', () => {
    const wrapper = mount(AppTextField, {
      props: { label: 'Password', type: 'password', autocomplete: 'current-password' },
    })

    expect(wrapper.find('input').attributes('autocomplete')).toBe('current-password')
    expect(wrapper.find('input').attributes('type')).toBe('password')
  })

  it('announces an error rather than only colouring the border', () => {
    const wrapper = mount(AppTextField, {
      props: { label: 'Password', error: 'A password must be at least 8 characters' },
    })

    const input = wrapper.find('input')
    expect(input.attributes('aria-invalid')).toBe('true')
    const described = input.attributes('aria-describedby')
    expect(described).toBeTruthy()
    expect(wrapper.find(`#${described}`).text()).toBe('A password must be at least 8 characters')
    expect(wrapper.find(`#${described}`).attributes('role')).toBe('alert')
  })

  it('shows a hint the same way but does not call it an error', () => {
    const wrapper = mount(AppTextField, {
      props: { label: 'Password', hint: 'At least 8 characters' },
    })

    expect(wrapper.find('input').attributes('aria-invalid')).toBe('false')
    expect(wrapper.text()).toContain('At least 8 characters')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('prefers the error over the hint when both are present', () => {
    const wrapper = mount(AppTextField, {
      props: { label: 'Password', hint: 'At least 8 characters', error: 'Too short' },
    })

    expect(wrapper.text()).toContain('Too short')
    expect(wrapper.text()).not.toContain('At least 8 characters')
  })
})
