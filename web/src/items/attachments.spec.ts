import { describe, expect, it } from 'vitest'

import { attachmentTitles, cleanLink, defaultTitle, holdsStoredFile } from '@/items/attachments'
import type { ItemEnvelope } from '@/stores/library'

function attachment(contentType: string, linkMode = 'imported_file'): ItemEnvelope {
  return {
    key: `K${contentType}`,
    version: 1,
    data: { itemType: 'attachment', linkMode, contentType },
    meta: {},
  }
}

const words = (key: string) => `«${key}»`

describe('defaultTitle', () => {
  it.each([
    ['application/pdf', 'PDF'],
    ['application/epub+zip', 'Ebook'],
    ['text/html', 'Webpage'],
    ['image/png', 'Image'],
    ['audio/mpeg', 'Audio'],
    ['video/mp4', 'Video'],
    ['text/plain', null],
    ['', null],
  ])('names %s %s, as the desktop does', (contentType, key) => {
    expect(defaultTitle(contentType, words)).toBe(key === null ? null : words(key))
  })
})

describe('attachmentTitles', () => {
  it('gives the first of its type under an item the type’s word', () => {
    expect(attachmentTitles([{ type: 'application/pdf' }], [], words)).toEqual(['«PDF»'])
  })

  it('leaves a second of the same type to be named after its file', () => {
    const siblings = [attachment('application/pdf')]

    expect(attachmentTitles([{ type: 'application/pdf' }], siblings, words)).toEqual([undefined])
  })

  it('counts a linked file but not a web link', () => {
    expect(
      attachmentTitles([{ type: 'application/pdf' }], [attachment('application/pdf', 'linked_file')], words),
    ).toEqual([undefined])
    expect(
      attachmentTitles([{ type: 'application/pdf' }], [attachment('application/pdf', 'linked_url')], words),
    ).toEqual(['«PDF»'])
  })

  it('counts files added together against each other', () => {
    const files = [{ type: 'application/pdf' }, { type: 'application/pdf' }, { type: 'image/png' }]

    expect(attachmentTitles(files, [], words)).toEqual(['«PDF»', undefined, '«Image»'])
  })

  it('names a file on its own after itself', () => {
    expect(attachmentTitles([{ type: 'application/pdf' }], null, words)).toEqual([undefined])
  })

  it('has no word for a type without one', () => {
    expect(attachmentTitles([{ type: 'text/plain' }], [], words)).toEqual([undefined])
  })
})

describe('holdsStoredFile', () => {
  it.each([
    ['imported_file', true],
    ['imported_url', true],
    ['linked_file', false],
    ['linked_url', false],
    ['embedded_image', false],
  ])('%s: %s', (linkMode, expected) => {
    expect(holdsStoredFile(attachment('application/pdf', linkMode))).toBe(expected)
  })
})

describe('cleanLink', () => {
  it('keeps an address as the parser writes it', () => {
    expect(cleanLink('  https://example.org/a b ')).toEqual({
      ok: true,
      url: 'https://example.org/a%20b',
    })
  })

  it('puts http:// in front of something that looks like a host', () => {
    expect(cleanLink('example.org/paper')).toEqual({ ok: true, url: 'http://example.org/paper' })
  })

  it('does not recognise words', () => {
    expect(cleanLink('not an address')).toEqual({ ok: false, reason: 'unrecognized' })
    expect(cleanLink('')).toEqual({ ok: false, reason: 'unrecognized' })
  })

  it('sends a file address elsewhere, as the desktop’s dialog does', () => {
    expect(cleanLink('file:///home/ada/paper.pdf')).toEqual({ ok: false, reason: 'file' })
  })

  it.each(['javascript:alert(1)', 'data:text/html,x', 'mailto:ada@example.org'])(
    'refuses %s',
    (text) => {
      expect(cleanLink(text)).toEqual({ ok: false, reason: 'scheme' })
    },
  )
})
