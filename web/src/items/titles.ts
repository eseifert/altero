import { getBaseMappedValue } from '@/items/labels'
import type { ItemEnvelope } from '@/stores/library'

// Cache previews by item data so rendering a long note does not repeatedly
// strip all its HTML. Keep the source as well, for edits made in place.
const noteTitles = new WeakMap<object, { source: string; title: string }>()

/** The item's title, or an empty string for the caller's translated fallback. */
export function getItemTitle(item: ItemEnvelope): string {
  if (item.data.itemType === 'note') {
    const source = item.data.note ?? ''
    let cached = noteTitles.get(item.data)
    if (!cached || cached.source !== source) {
      cached = { source, title: source.replace(/<[^>]+>/g, ' ').trim().slice(0, 120) }
      noteTitles.set(item.data, cached)
    }
    return cached.title
  }

  const title = getBaseMappedValue(item.data, 'title')
  return typeof title === 'string' ? title : ''
}
