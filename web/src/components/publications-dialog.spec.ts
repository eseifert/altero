import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PublicationsDialog from './PublicationsDialog.vue'

/**
 * The wizard, against the walk `publicationsDialog.js` describes.
 *
 * What is checked is which questions are asked and what the answers add up to
 * — not the markup. Publishing somebody's work under a licence they did not
 * choose is the failure this file exists to catch.
 */

const WORK = { title: 'The Dispossessed', hasFiles: true, hasNotes: true, hasRights: false }

function open(props: Partial<typeof WORK> = {}) {
  return mount(PublicationsDialog, { props: { ...WORK, ...props } })
}

type Wrapper = ReturnType<typeof open>

/** Tick the checkbox or radio whose label says `label`. */
async function choose(wrapper: Wrapper, label: string) {
  const found = wrapper.findAll('.dialog__check').find((entry) => entry.text().includes(label))
  if (!found) throw new Error(`No control labelled ${label}`)
  await found.get('input').setValue(true)
}

/** The button that advances or finishes, whatever it currently says. */
function next(wrapper: Wrapper) {
  return wrapper.get('button[type="submit"]')
}

/* The form is submitted rather than the button clicked: jsdom does not turn a
   click on a submit button into a submit event, and the dialog's own handler
   is on the form. */
async function press(wrapper: Wrapper) {
  await wrapper.get('.dialog__body').trigger('submit')
  await wrapper.vm.$nextTick()
}

/** Get through the first page, which every path has to. */
async function claim(wrapper: Wrapper, { files = false, notes = false } = {}) {
  if (files) await choose(wrapper, 'Include files')
  if (notes) await choose(wrapper, 'Include notes')
  await choose(wrapper, 'I created this work')
}

describe('the My Publications wizard', () => {
  it('will not publish anything until authorship is claimed', async () => {
    /* `wizard.canAdvance = id('confirm-authorship-checkbox').checked` — the
       one control in the client's dialog that has to be answered. */
    const wrapper = open()

    expect(next(wrapper).attributes('disabled')).toBeDefined()

    await choose(wrapper, 'I created this work')

    expect(next(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('says what it will do rather than only "Next"', async () => {
    const wrapper = open()

    expect(next(wrapper).text()).toBe('Add to My Publications')

    await choose(wrapper, 'Include files')

    expect(next(wrapper).text()).toBe('Next: Sharing')
  })

  it('offers no files to include when there are none', () => {
    const wrapper = open({ hasFiles: false, hasNotes: false })

    const boxes = wrapper.findAll('.dialog__check input')
    expect(boxes[0].attributes('disabled')).toBeDefined()
    expect(boxes[1].attributes('disabled')).toBeDefined()
  })

  it('publishes without asking about a licence when no files go along', async () => {
    /* Nothing is being licensed, so nothing is written to the Rights field:
       `io.license` stays undefined in the client on this path. */
    const wrapper = open()
    await claim(wrapper, { notes: true })

    await press(wrapper)

    expect(wrapper.emitted('submit')).toEqual([
      [{ includeFiles: false, includeNotes: true, license: null, keepRights: false }],
    ])
  })

  it('names the larger claim when files are included', async () => {
    const wrapper = open()

    expect(wrapper.text()).toContain('I created this work.')

    await choose(wrapper, 'Include files')

    expect(wrapper.text()).toContain('have the rights to distribute')
  })

  it('asks about sharing once files are included, and finishes on reserved rights', async () => {
    const wrapper = open()
    await claim(wrapper, { files: true })

    await press(wrapper)

    expect(wrapper.text()).toContain('Choose how your work may be shared')
    expect(next(wrapper).text()).toBe('Add to My Publications')

    await press(wrapper)

    expect(wrapper.emitted('submit')).toEqual([
      [{ includeFiles: true, includeNotes: false, license: 'reserved', keepRights: false }],
    ])
  })

  it('finishes on the public domain without a further question', async () => {
    const wrapper = open()
    await claim(wrapper, { files: true })
    await press(wrapper)

    await choose(wrapper, 'public domain')
    await press(wrapper)

    expect(wrapper.emitted('submit')![0][0]).toMatchObject({ license: 'cc0' })
  })

  it('warns that a public domain dedication cannot be undone', async () => {
    const wrapper = open()
    await claim(wrapper, { files: true })
    await press(wrapper)

    await choose(wrapper, 'public domain')

    expect(wrapper.text()).toContain('cannot be undone')
    expect(wrapper.text()).toContain('CC0 1.0 Universal Public Domain Dedication')
  })

  it('asks the two Creative Commons questions and arrives at the licence they make', async () => {
    const wrapper = open()
    await claim(wrapper, { files: true })
    await press(wrapper)
    await choose(wrapper, 'under a Creative Commons license')

    expect(next(wrapper).text()).toBe('Next: Choose a License')
    await press(wrapper)

    /* The defaults are the client's, and they are the most restrictive of each
       pair: no adaptations, no commercial use. */
    expect(wrapper.text()).toContain(
      'Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License',
    )

    await choose(wrapper, 'Yes, as long as others share alike')
    await press(wrapper)

    expect(wrapper.emitted('submit')![0][0]).toMatchObject({ license: 'cc-by-nc-sa' })
  })

  it('shows the licence under the name the item will carry', async () => {
    const wrapper = open()
    await claim(wrapper, { files: true })
    await press(wrapper)
    await choose(wrapper, 'under a Creative Commons license')
    await press(wrapper)
    const radios = wrapper.findAll('.dialog__check input')
    await radios[2].setValue(true) // Adaptations: yes
    await radios[4].setValue(true) // Commercial: yes

    expect(wrapper.get('.publish__license').text()).toBe(
      'Creative Commons Attribution 4.0 International License',
    )
    expect(wrapper.get('.publish__license a').attributes('href')).toBe(
      'https://creativecommons.org/licenses/by/4.0/',
    )
  })

  it('offers to keep the Rights field only when there is one', async () => {
    const wrapper = open({ hasRights: false })
    await claim(wrapper, { files: true })
    await press(wrapper)

    expect(wrapper.text()).not.toContain('Keep the existing Rights field')
  })

  it('stops asking about licences once the Rights field is to be kept', async () => {
    /* `updateSharingPage`: choosing a licence that will not be written is a
       question with no consequence, so the client hides it. */
    const wrapper = open({ hasRights: true })
    await claim(wrapper, { files: true })
    await press(wrapper)

    await choose(wrapper, 'Keep the existing Rights field')

    expect(wrapper.text()).not.toContain('Would you like to allow your work to be shared')
    expect(next(wrapper).text()).toBe('Add to My Publications')

    await press(wrapper)

    expect(wrapper.emitted('submit')).toEqual([
      [{ includeFiles: true, includeNotes: false, license: null, keepRights: true }],
    ])
  })

  it('can go back to change an answer', async () => {
    const wrapper = open()
    await claim(wrapper, { files: true })
    await press(wrapper)

    await wrapper.findAll('button').find((entry) => entry.text() === 'Back')!.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Include files')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('can be given up on at any page', async () => {
    const wrapper = open()
    await claim(wrapper, { files: true })
    await press(wrapper)

    await wrapper.findAll('button').find((entry) => entry.text() === 'Cancel')!.trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('submit')).toBeUndefined()
  })
})
