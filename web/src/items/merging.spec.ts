import { describe, expect, it } from 'vitest'

import type { ItemEnvelope } from '@/stores/library'
import { mergeFields, oldestFirst } from './merging'

const row = (key: string, data: Record<string, unknown>): ItemEnvelope => ({
  key, version: 1, meta: {}, data: { itemType: 'book', ...data },
})

describe('merge alternatives', () => {
  it('defaults to the oldest item with a deterministic tie break', () => {
    const rows = [row('NEW', { dateAdded: '2026-01-01T00:00:00Z' }),
      row('OLD', { dateAdded: '2020-01-01T00:00:00Z' }), row('AAA', { dateAdded: '2020-01-01T00:00:00Z' })]
    expect(oldestFirst(rows).map((item) => item.key)).toEqual(['AAA', 'OLD', 'NEW'])
    expect(rows[0]!.key).toBe('NEW')
  })

  it('offers distinct schema values including an empty master, excluding structure and access dates', () => {
    const rows = [row('A', { title: '', accessDate: '2020-01-01', tags: ['a'] }),
      row('B', { title: 'Chosen', accessDate: '2025-01-01', tags: ['b'] }), row('C', { title: 'Chosen' })]
    expect(mergeFields(rows, { fields: ['title', 'accessDate', 'ISBN'], creatorTypes: ['author'] }))
      .toEqual([{ name: 'title', values: ['', 'Chosen'] }])
  })

  it('keeps creator order and roles as a whole-list choice', () => {
    const author = { creatorType: 'author', name: 'A collective' }
    const editor = { creatorType: 'editor', firstName: 'Jo', lastName: 'Smith' }
    const rows = [row('A', { creators: [author, editor] }), row('B', { creators: [editor, author] }), row('C', {})]
    expect(mergeFields(rows, { fields: [], creatorTypes: ['author', 'editor'] }))
      .toEqual([{ name: 'creators', values: [[author, editor], [editor, author], []] }])
  })
})
