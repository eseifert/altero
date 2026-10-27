import type { ItemEnvelope } from '@/stores/library'

/*
 * What the desktop decides about an attachment as it is added, decided the
 * same way here: what a new file is called, and whether an address typed into
 * *Attach Web Link…* is one.
 */

/**
 * The words a first attachment of a kind is called under its item, by content type.
 *
 * `Zotero.Item._getDefaultTitleForAttachmentContentType`, whose words are
 * `file-type-*` in the desktop's catalogue; these are the same words in this
 * interface's. `null` for a type with none, which is named after its file.
 */
export function defaultTitle(contentType: string, t: (key: string) => string): string | null {
  if (!contentType) return null
  if (contentType === 'application/pdf') return t('PDF')
  if (contentType === 'application/epub+zip') return t('Ebook')
  if (contentType === 'text/html') return t('Webpage')
  if (contentType.startsWith('image/')) return t('Image')
  if (contentType.startsWith('audio/')) return t('Audio')
  if (contentType.startsWith('video/')) return t('Video')
  return null
}

/** Whether an attachment holds a file, stored or linked, as `isFileAttachment` asks. */
export function isFileAttachment(item: ItemEnvelope): boolean {
  return item.data.itemType === 'attachment' && item.data.linkMode !== 'linked_url'
}

/** Whether this attachment's file is stored on the server, and so can be replaced there. */
export function holdsStoredFile(item: ItemEnvelope): boolean {
  return (
    item.data.itemType === 'attachment' &&
    (item.data.linkMode === 'imported_file' || item.data.linkMode === 'imported_url')
  )
}

/**
 * The title each of ``files`` is given, or `undefined` for the server's default.
 *
 * `Zotero.Item.setAutoAttachmentTitle`: the only attachment of its content type
 * under an item takes that type's word ("PDF"), and any other is named after
 * its file without the extension -- which is what the server names one sent
 * with no title, so that case is left to it. ``siblings`` are the item's
 * children; `null` for a file on its own, which is never first of its type.
 * Files added together count against each other, as they would if the desktop
 * had added them one after another.
 */
export function attachmentTitles(
  files: readonly { type: string }[],
  siblings: readonly ItemEnvelope[] | null,
  t: (key: string) => string,
): (string | undefined)[] {
  if (siblings === null) return files.map(() => undefined)
  const taken = new Set(
    siblings.filter(isFileAttachment).map((child) => String(child.data.contentType ?? '')),
  )
  return files.map((file) => {
    const title = taken.has(file.type) ? null : defaultTitle(file.type, t)
    taken.add(file.type)
    return title ?? undefined
  })
}

/** Schemes the desktop will not link to; see the server's `UNLINKABLE_SCHEMES`. */
const UNLINKABLE = new Set(['javascript:', 'data:', 'chrome:', 'resource:', 'mailto:'])

export type CleanedLink =
  | { ok: true; url: string }
  | { ok: false; reason: 'unrecognized' | 'file' | 'scheme' }

/**
 * What *Attach Web Link…* makes of what was typed.
 *
 * `Zotero.Utilities.cleanURL` with ``tryHttp``: an address as the URL parser
 * reads it, or, if it reads none, the same with `http://` in front when it
 * looks like a host name. A `file:` address is refused as the desktop's dialog
 * refuses it, pointing at the linked-file command this interface has no use
 * for, and the schemes `linkFromURL` refuses are refused before the server is
 * asked.
 */
export function cleanLink(text: string): CleanedLink {
  const trimmed = text.trim()
  if (!trimmed) return { ok: false, reason: 'unrecognized' }
  let url = parse(trimmed)
  if (url === null && /\w\.\w/.test(trimmed)) url = parse(`http://${trimmed}`)
  if (url === null) return { ok: false, reason: 'unrecognized' }
  if (url.protocol === 'file:') return { ok: false, reason: 'file' }
  if (UNLINKABLE.has(url.protocol)) return { ok: false, reason: 'scheme' }
  return { ok: true, url: url.href }
}

function parse(text: string): URL | null {
  try {
    return new URL(text)
  } catch {
    return null
  }
}
