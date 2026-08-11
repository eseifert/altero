/**
 * The formats a set of items can be written out in.
 *
 * Four, against the desktop client's dozen, because these are the four the
 * server can write: BibTeX, BibLaTeX and RIS are `altero/cite/export.py`, and
 * CSL JSON is what a citation is rendered from. Everything else the client
 * offers — Zotero RDF, MODS, Endnote XML, the note translators — is a
 * JavaScript translator run by a translation server that altero has no
 * equivalent of.
 *
 * The names are not translated and are not in the catalogues: BibTeX is BibTeX
 * in every language, and the client's own format menu leaves them alone too.
 * The order is the client's — it sorts its translator list by label — so
 * somebody who has learnt where RIS sits in that menu finds it in the same
 * place here.
 */

export interface ExportFormat {
  /** What the server's `format` parameter calls it. */
  id: string
  /** What the menu shows. A proper noun, so it is not a message. */
  label: string
}

export const EXPORT_FORMATS: ExportFormat[] = [
  { id: 'biblatex', label: 'BibLaTeX' },
  { id: 'bibtex', label: 'BibTeX' },
  { id: 'csljson', label: 'CSL JSON' },
  { id: 'ris', label: 'RIS' },
]

/**
 * Which one was chosen last, remembered per device.
 *
 * The client keeps `export.lastTranslator` for the same reason: a person
 * exports into the same pipeline every time, and picking BibTeX out of a menu
 * for the four hundredth time is not a choice, it is a toll.
 */
export const EXPORT_FORMAT_STORAGE_KEY = 'altero.export-format'

/** What is offered before anyone has chosen: the one a bibliography is made of. */
export const DEFAULT_EXPORT_FORMAT = 'bibtex'

export function rememberedFormat(): string {
  try {
    const stored = localStorage.getItem(EXPORT_FORMAT_STORAGE_KEY)
    return EXPORT_FORMATS.some((format) => format.id === stored) && stored
      ? stored
      : DEFAULT_EXPORT_FORMAT
  } catch {
    // Private browsing on older Safari throws rather than refusing quietly.
    return DEFAULT_EXPORT_FORMAT
  }
}

export function rememberFormat(id: string): void {
  try {
    localStorage.setItem(EXPORT_FORMAT_STORAGE_KEY, id)
  } catch {
    // Then it is not remembered. Nothing else about the export depends on it.
  }
}

/**
 * Item types none of these formats has an entry for.
 *
 * A note is not a work, an attachment is a file belonging to one, and an
 * annotation belongs to the attachment. The server leaves them out of what it
 * writes; this is here so the interface does not offer an export that would
 * come back empty — which is what the client does too, by hiding every format
 * but its note translators when a selection is nothing but notes.
 */
const UNCITED = new Set(['note', 'attachment', 'annotation'])

export function exportable(itemType: string): boolean {
  return !UNCITED.has(itemType)
}
