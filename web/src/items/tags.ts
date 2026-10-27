import type { TagColor } from '@/stores/library'

/*
 * The order Zotero draws an item's tags in: coloured ones first, in the order
 * their colours were assigned; then any containing an emoji; then the rest
 * alphabetically (`Zotero.Tags.compareTagsOrder`).
 */

/**
 * `Zotero.Utilities.Internal.containsEmoji`, which needs the `v` flag. Built at
 * run time, because a browser older than Safari 17 cannot even parse that
 * literal; those fall back to the plainer pictographic class.
 */
const EMOJI: RegExp = (() => {
  try {
    return new RegExp(
      '\\p{RGI_Emoji}|[[\\p{Extended_Pictographic}[\\p{So}&&[☀-➿\\u{1F000}-\\u{1FAFF}]]]--[©®™\\u{1F1E6}-\\u{1F1FF}]]',
      'v',
    )
  } catch {
    return /\p{Extended_Pictographic}/u
  }
})()

export function containsEmoji(text: string): boolean {
  return EMOJI.test(text)
}

/** Each coloured tag's colour and place, by name. */
export function colorIndex(colors: TagColor[]): Map<string, { color: string; position: number }> {
  return new Map(colors.map((entry, position) => [entry.name, { color: entry.color, position }]))
}

export function compareTags(
  a: string,
  b: string,
  colors: Map<string, { position: number }>,
  locale: string,
): number {
  const first = colors.get(a)
  const second = colors.get(b)
  if (first && !second) return -1
  if (!first && second) return 1
  if (first && second) return first.position - second.position
  const emojiA = containsEmoji(a)
  const emojiB = containsEmoji(b)
  if (emojiA !== emojiB) return emojiA ? -1 : 1
  return a.localeCompare(b, locale, { sensitivity: 'base' })
}
