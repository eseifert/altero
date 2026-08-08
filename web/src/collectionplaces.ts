import type { CollectionNode } from '@/stores/library'

/**
 * A place a collection can sit: the library's top level, or another collection.
 *
 * The settings dialog moves a collection by naming where it goes rather than by
 * dragging it there, so it needs the tree flattened into a list of choices with
 * the depth each one sits at.
 */
export interface Place {
  /** The collection to sit inside, or ``null`` for the library's top level. */
  key: string | null
  label: string
  /** How deep in the tree it is, for the indent. Zero is the library itself. */
  depth: number
}

/**
 * Everywhere ``moving`` could go, the library first.
 *
 * The collection being moved is left out along with everything under it. A
 * collection inside itself is a loop: the branch still exists and nothing
 * reaches it, because the sidebar draws the tree from parents and neither end
 * of the loop has one above it. The server refuses the write; this makes sure
 * the reader is never offered it.
 *
 * ``moving`` is optional because the same list answers "where shall this go"
 * for something that is not in the tree yet.
 */
export function placesFor(
  collections: CollectionNode[],
  library: string,
  moving?: string | null,
): Place[] {
  const places: Place[] = [{ key: null, label: library, depth: 0 }]

  const walk = (nodes: CollectionNode[], depth: number): void => {
    for (const node of nodes) {
      if (node.key === moving) continue
      places.push({ key: node.key, label: node.data.name, depth })
      walk(node.children, depth + 1)
    }
  }
  walk(collections, 1)

  return places
}
