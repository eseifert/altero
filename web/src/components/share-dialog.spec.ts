import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { CollectionShare } from '@/stores/shares'

import ShareDialog from './ShareDialog.vue'

const clipboard = vi.fn()

function share(id = 1): CollectionShare {
  return {
    id, collection: 'AAAA2345', collectionName: 'Reading', subcollections: true,
    files: true, created: '2026-11-04T00:00:00Z', expires: null, lastUsed: null,
    createdBy: 1, url: `https://example.test/app/shared/${id}`,
  }
}

function open() {
  return mount(ShareDialog, { props: { collectionName: 'Reading', shares: [], issued: share() } })
}

beforeEach(() => {
  clipboard.mockReset()
  vi.stubGlobal('navigator', { clipboard: { writeText: clipboard } })
})
afterEach(() => vi.unstubAllGlobals())

it('announces Copied only after the clipboard accepts the displayed link', async () => {
  let finish!: () => void
  clipboard.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve }))
  const wrapper = open()
  await wrapper.get('.share__url-row button').trigger('click')
  expect(clipboard).toHaveBeenCalledWith(share().url)
  expect(wrapper.get('.share__url-row button').text()).toBe('Copy')
  finish()
  await flushPromises()
  expect(wrapper.get('[role="status"]').text()).toBe('Copied')
})

it('leaves the link available for manual copying when clipboard access is refused', async () => {
  clipboard.mockRejectedValue(new Error('Permission denied'))
  const wrapper = open()
  await wrapper.get('.share__url-row button').trigger('click')
  await flushPromises()
  expect(wrapper.get('.share__url-row button').text()).toBe('Copy')
  expect((wrapper.get('#share-url').element as HTMLInputElement).value).toBe(share().url)
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
})

it('does not acknowledge a replacement link when an older copy finishes', async () => {
  let finish!: () => void
  clipboard.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve }))
  const wrapper = open()
  await wrapper.get('.share__url-row button').trigger('click')
  await wrapper.setProps({ issued: share(2) })
  finish()
  await flushPromises()
  expect(wrapper.get('.share__url-row button').text()).toBe('Copy')
})

it('does not let an earlier refusal erase the latest successful copy', async () => {
  let refuse!: (error: Error) => void
  clipboard.mockImplementationOnce(() => new Promise<void>((_, reject) => { refuse = reject }))
    .mockResolvedValue(undefined)
  const wrapper = open()
  const button = wrapper.get('.share__url-row button')
  await button.trigger('click')
  await button.trigger('click')
  await flushPromises()
  expect(button.text()).toBe('Copied')
  refuse(new Error('Earlier refusal'))
  await flushPromises()
  expect(button.text()).toBe('Copied')
})
