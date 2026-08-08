import { describe, expect, it } from 'vitest'

import { placesFor } from './collectionplaces'
import type { CollectionNode } from './stores/library'

function node(key: string, name: string, children: CollectionNode[] = []): CollectionNode {
  return {
    key,
    version: 1,
    data: { key, name, parentCollection: false },
    meta: { numCollections: children.length, numItems: 0 },
    children,
  }
}

const TREE = [
  node('AAAA2345', 'Papers', [node('BBBB2345', 'Drafts', [node('CCCC2345', 'Old')])]),
  node('DDDD2345', 'Books'),
]

describe('the places a collection can be moved to', () => {
  it('leads with the library, which is what having no parent means', () => {
    expect(placesFor(TREE, 'Ada')[0]).toEqual({ key: null, label: 'Ada', depth: 0 })
  })

  it('flattens the tree in the order it is drawn, with the depth of each', () => {
    expect(placesFor(TREE, 'Ada')).toEqual([
      { key: null, label: 'Ada', depth: 0 },
      { key: 'AAAA2345', label: 'Papers', depth: 1 },
      { key: 'BBBB2345', label: 'Drafts', depth: 2 },
      { key: 'CCCC2345', label: 'Old', depth: 3 },
      { key: 'DDDD2345', label: 'Books', depth: 1 },
    ])
  })

  it('leaves out the collection being moved', () => {
    const offered = placesFor(TREE, 'Ada', 'DDDD2345').map((place) => place.key)

    expect(offered).not.toContain('DDDD2345')
  })

  it('leaves out everything under it as well', () => {
    /* The loop that takes a branch out of the tree: it still exists, and
       nothing reaches it, because the sidebar draws from parents and neither
       end of the loop has one above it. */
    const offered = placesFor(TREE, 'Ada', 'AAAA2345').map((place) => place.key)

    expect(offered).toEqual([null, 'DDDD2345'])
  })
})
