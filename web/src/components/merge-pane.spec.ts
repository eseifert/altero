import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { ItemEnvelope, MergeSnapshot } from '@/stores/library'
import MergePane from './MergePane.vue'

const { outlineMock } = vi.hoisted(() => ({ outlineMock: vi.fn() }))
vi.mock('@/items/labels', async (original) => ({
  ...(await original<typeof import('@/items/labels')>()),
  loadLabels: vi.fn().mockResolvedValue(undefined), fieldLabel: (name: string) => name,
  typeOutline: outlineMock,
}))
const row = (key: string, title: string, dateAdded: string): ItemEnvelope => ({
  key, version: 3, meta: {}, data: { itemType: 'book', title, dateAdded },
})
const newer = row('NEWER234', 'New title', '2025-01-01T00:00:00Z')
const older = row('OLDER234', 'Old title', '2020-01-01T00:00:00Z')
const snapshot: MergeSnapshot = { libraryId: 1, version: 7, items: [newer, older] }
beforeEach(() => {
  setActivePinia(createPinia())
  outlineMock.mockReturnValue({ fields: ['title', 'ISBN'], creatorTypes: ['author'] })
})

async function open(items = snapshot) {
  const load = vi.fn().mockResolvedValue(structuredClone(items))
  const merge = vi.fn().mockResolvedValue(undefined)
  const wrapper = mount(MergePane, { props: { keys: ['NEWER234', 'OLDER234'], load, merge } })
  await flushPromises()
  return { wrapper, load, merge }
}

describe('merging selected duplicates', () => {
  it('defaults to the oldest master and requires a separate confirmation', async () => {
    const { wrapper, merge } = await open()
    expect((wrapper.get('select[name="merge-master"]').element as HTMLSelectElement).value).toBe('OLDER234')
    await wrapper.get('select[name="merge-title"]').setValue('1')
    await wrapper.get('[data-merge-review]').trigger('click')
    expect(merge).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Other versions will be moved to the trash.')
    await wrapper.get('[data-merge-confirm]').trigger('click')
    await flushPromises()
    expect(merge).toHaveBeenCalledWith(snapshot, 'OLDER234', { title: 'New title' })
  })

  it('cancels confirmation without losing field choices, and a new master resets them', async () => {
    const { wrapper, merge } = await open()
    await wrapper.get('select[name="merge-title"]').setValue('1')
    await wrapper.get('[data-merge-review]').trigger('click')
    await wrapper.get('[data-merge-cancel]').trigger('click')
    expect(merge).not.toHaveBeenCalled()
    expect((wrapper.get('select[name="merge-title"]').element as HTMLSelectElement).value).toBe('1')
    await wrapper.get('select[name="merge-master"]').setValue('NEWER234')
    expect((wrapper.get('select[name="merge-title"]').element as HTMLSelectElement).value).toBe('1')
    await wrapper.get('select[name="merge-master"]').setValue('OLDER234')
    expect((wrapper.get('select[name="merge-title"]').element as HTMLSelectElement).value).toBe('0')
  })

  it('freezes a stale draft until explicit reload; selection reordering does not reread it', async () => {
    const { wrapper, load, merge } = await open()
    merge.mockRejectedValueOnce(new ApiError('Changed', 412))
    await wrapper.setProps({ keys: ['OLDER234', 'NEWER234'] })
    expect(load).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-merge-review]').trigger('click')
    await wrapper.get('[data-merge-confirm]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Changed elsewhere while you were editing.')
    expect(wrapper.find('[data-merge-review]').exists()).toBe(false)
    expect(merge).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-merge-reload]').trigger('click')
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-merge-review]').exists()).toBe(true)
  })

  it('explains why mixed item types cannot merge', async () => {
    const mixed = structuredClone(snapshot)
    mixed.items[0]!.data.itemType = 'journalArticle'
    const { wrapper } = await open(mixed)
    expect(wrapper.text()).toContain('Merged items must all be of the same item type.')
    expect(wrapper.get('[data-merge-review]').attributes('disabled')).toBeDefined()
  })

  it('cannot merge without the item schema', async () => {
    outlineMock.mockReturnValue(null)
    const { wrapper } = await open()
    expect(wrapper.get('[role="alert"]').text()).toContain('Could not load the item fields.')
    expect(wrapper.find('[data-merge-review]').exists()).toBe(false)
  })

  it('offers inspection and subset selection with ordinary toolbar clicks', async () => {
    const { wrapper, load } = await open()
    await wrapper.get('[aria-label="Edit"]').trigger('click')
    await wrapper.get('[data-merge-inspect="NEWER234"]').trigger('click')
    expect(wrapper.emitted('inspect')).toEqual([['NEWER234']])
    await wrapper.get('[aria-label="Select"]').trigger('click')
    await wrapper.get('input[type="checkbox"][value="NEWER234"]').setValue(false)
    expect(wrapper.emitted('selection')?.at(-1)).toEqual([['OLDER234']])
    await wrapper.setProps({ selected: ['OLDER234'] })
    expect(wrapper.get('[data-merge-review]').attributes('disabled')).toBeDefined()
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('merges only included members while keeping the original review version', async () => {
    const extra = row('EXTRA234', 'Excluded candidate', '2021-01-01T00:00:00Z')
    const { wrapper, merge } = await open({ ...snapshot, items: [...snapshot.items, extra] })
    await wrapper.setProps({ selected: ['NEWER234', 'OLDER234'] })
    expect(wrapper.get('select[name="merge-title"]').text()).not.toContain('Excluded candidate')
    await wrapper.get('[data-merge-review]').trigger('click')
    await wrapper.get('[data-merge-confirm]').trigger('click')
    await flushPromises()
    expect(merge).toHaveBeenCalledWith(snapshot, 'OLDER234', { title: 'Old title' })
  })

  it('keeps inspection and export available in a read-only group', async () => {
    const { wrapper } = await open()
    await wrapper.setProps({ writable: false, removable: false })
    expect(wrapper.get('[data-merge-review]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="Edit"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[aria-label="Export…"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Move to trash"]').exists()).toBe(false)
  })

  it('disables confirmation and dismissal while the write is pending', async () => {
    const { wrapper, merge } = await open()
    let finish!: () => void
    merge.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve }))
    await wrapper.get('[data-merge-review]').trigger('click')
    await wrapper.get('[data-merge-confirm]').trigger('click')
    expect(wrapper.get('[data-merge-confirm]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="Clear the selection"]').attributes('disabled')).toBeDefined()
    finish()
    await flushPromises()
  })
})
