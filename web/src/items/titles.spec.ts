import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getBaseMappedValue, loadLabels, resetLabels } from '@/items/labels'
import type { ItemEnvelope } from '@/stores/library'

import { getItemTitle, noteToTitle } from './titles'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))
vi.mock('@/api/client', () => ({ request: requestMock }))

function item(data: ItemEnvelope['data']): ItemEnvelope {
  return { key: 'AAAA2345', version: 1, data, meta: {} }
}

beforeEach(() => {
  resetLabels()
  requestMock.mockReset()
})

describe('shared item titles', () => {
  it('reads ordinary titles before the schema arrives', () => {
    expect(getItemTitle(item({ itemType: 'book', title: 'A book' }))).toBe('A book')
  })

  it('uses schema mappings for new types and fields without a hard-coded list', async () => {
    requestMock.mockResolvedValue({ mappings: { newType: { title: 'caption', date: 'issued' } } })
    await loadLabels()
    const data = { itemType: 'newType', caption: 'A new title', issued: '2026' }

    expect(getItemTitle(item(data))).toBe('A new title')
    expect(getBaseMappedValue(data, 'date')).toBe('2026')
  })

  it.each([undefined, '', null, 123])(
    'leaves an absent or invalid title (%s) to the translated fallback',
    (title) => {
      expect(getItemTitle(item({ itemType: 'book', title } as ItemEnvelope['data']))).toBe('')
    },
  )

  it('keeps note previews short and updates them when the note changes', () => {
    const note = item({ itemType: 'note', note: `<p>${'a'.repeat(150)}</p>` })
    expect(getItemTitle(note)).toBe('a'.repeat(120))

    note.data.note = '<p>Updated <b>note</b></p>'
    expect(getItemTitle(note)).toBe('Updated note')
    note.data.note = '<p></p>'
    expect(getItemTitle(note)).toBe('')
  })
})

// What `Zotero.Utilities.Item.noteToTitle` (zotero/utilities `4051881`) answers for
// each, run under Node with jsdom as its own Node branch does.
describe("a note's title", () => {
  it.each([
    ['<div data-schema-version="9"><h1>Heading</h1>\n<p>Body</p>\n</div>', 'Heading'],
    ['<p>One<br>two</p>', 'One two'],
    ['<p>Fish &amp; chips &lt;3</p>', 'Fish & chips <3'],
    ['<blockquote>\n<p>Quoted</p>\n</blockquote>', 'Quoted'],
    ['<p>a    b</p>', 'a b'],
    ['plain text\nsecond line', 'plain text'],
    ['', ''],
  ])('%s', (html, title) => {
    expect(noteToTitle(html)).toBe(title)
  })

  it('stops at a line break when asked', () => {
    expect(noteToTitle('<p>One<br>two</p>', { stopAtLineBreak: true })).toBe('One')
  })

  it('runs nothing in the note it reads', () => {
    const fired = vi.fn()
    ;(window as any).fired = fired
    noteToTitle('<p><img src="x" onerror="window.fired()">x</p>')
    expect(fired).not.toHaveBeenCalled()
  })
})
