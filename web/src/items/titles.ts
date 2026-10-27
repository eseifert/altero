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
      cached = { source, title: noteToTitle(source) }
      noteTitles.set(item.data, cached)
    }
    return cached.title
  }

  const title = getBaseMappedValue(item.data, 'title')
  return typeof title === 'string' ? title : ''
}

/** What `unescapeHTML` makes of markup: its text, runs of spaces made one. */
function unescapeHTML(html: string): string {
  if (!html.includes('<') && !html.includes('&')) return html
  // Parsed into a document of its own, which loads nothing and runs nothing;
  // the original sets `innerHTML` on an element of the page.
  const text = new DOMParser().parseFromString(html, 'text/html').body.textContent ?? ''
  return text.replace(/ {2,}/g, ' ')
}

/**
 * A note's title: its first line, at most 120 characters.
 *
 * `Zotero.Utilities.Item.noteToTitle` from zotero/utilities, which the
 * desktop uses for the item list, ported as it is.
 */
export function noteToTitle(html: string, options: { stopAtLineBreak?: boolean } = {}): string {
  const MAX_TITLE_LENGTH = 120
  const original = html
  let text = html.trim()
  // Add line breaks after block elements
  text = text.replace(/(<\/(h\d|p|div)+>)/g, '$1\n')
  text = options.stopAtLineBreak ? text.replace(/<br\s*\/?>/g, '\n') : text.replace(/<br\s*\/?>/g, ' ')
  text = unescapeHTML(text)

  // If first line is just an opening HTML tag, remove it
  if (/^<[^>\n]+[^/]>\n/.test(original)) {
    text = text.trim()
  }

  let title = text.substring(0, MAX_TITLE_LENGTH)
  const ln = title.indexOf('\n')
  if (ln > -1 && ln < MAX_TITLE_LENGTH) {
    title = title.substring(0, ln)
  }
  return title
}
