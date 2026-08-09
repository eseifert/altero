import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import RightsDialog from './RightsDialog.vue'

/**
 * Changing what an item says about its rights.
 *
 * The desktop client does this in its Info pane, where Rights is an ordinary
 * field. Here it is a picker over the licences the publishing wizard offers,
 * because typing "Creative Commons Attribution 4.0 International License"
 * exactly right is not a thing to ask of anybody — with free text kept for
 * everything a Rights field otherwise says.
 */

function open(rights = '') {
  return mount(RightsDialog, { props: { title: 'The Dispossessed', rights } })
}

type Wrapper = ReturnType<typeof open>

function save(wrapper: Wrapper) {
  return wrapper.get('.dialog__body').trigger('submit')
}

describe('the rights dialog', () => {
  it('offers every licence the wizard offers, by code and by name', () => {
    const options = open()
      .findAll('option')
      .map((entry) => entry.text())

    expect(options[0]).toBe('All rights reserved')
    expect(options[1]).toBe('CC BY — Creative Commons Attribution 4.0 International License')
    expect(options).toContain('CC0 — CC0 1.0 Universal Public Domain Dedication')
  })

  it('opens on the licence the item already carries', () => {
    const wrapper = open('Creative Commons Attribution 4.0 International License')

    expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('cc-by')
    expect(wrapper.find('input[type="text"]').exists()).toBe(false)
  })

  it('stores the licence by its full name, which is what Rights holds', async () => {
    const wrapper = open()

    await wrapper.get('select').setValue('cc-by')
    await save(wrapper)

    expect(wrapper.emitted('submit')).toEqual([
      ['Creative Commons Attribution 4.0 International License'],
    ])
  })

  it('keeps anything else as free text, and says so', async () => {
    /* Rights holds "© 1974 the author" as readily as a licence, and an item
       synced from a client may say anything at all. */
    const wrapper = open('© 1974 the author')

    expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('custom')
    expect((wrapper.get('input[type="text"]').element as HTMLInputElement).value).toBe(
      '© 1974 the author',
    )

    await wrapper.get('input[type="text"]').setValue('© 1974, all rights reserved')
    await save(wrapper)

    expect(wrapper.emitted('submit')).toEqual([['© 1974, all rights reserved']])
  })

  it('can empty the field, which is a thing to be able to say', async () => {
    const wrapper = open('© 1974 the author')

    await wrapper.get('input[type="text"]').setValue('   ')
    await save(wrapper)

    expect(wrapper.emitted('submit')).toEqual([['']])
  })

  it('shows what will be stored when a licence is picked', async () => {
    const wrapper = open()

    await wrapper.get('select').setValue('cc-by-nc-sa')

    expect(wrapper.text()).toContain(
      'Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License',
    )
  })
})
