/**
 * The formats a set of items can be written out in.
 *
 * All of them the server writes, which is every export format zotero.org
 * serves: `altero/cite/formats/` is a port of the same translators the desktop
 * client runs, so a file exported here is the file exported there. The only
 * thing the client offers and this does not is its note translators, which
 * write a note rather than a bibliography.
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
  { id: 'rdf_bibliontology', label: 'Bibliontology RDF' },
  { id: 'bibtex', label: 'BibTeX' },
  { id: 'bookmarks', label: 'Bookmarks' },
  { id: 'coins', label: 'COinS' },
  { id: 'csljson', label: 'CSL JSON' },
  { id: 'csv', label: 'CSV' },
  { id: 'endnote_xml', label: 'Endnote XML' },
  { id: 'mods', label: 'MODS' },
  { id: 'refer', label: 'Refer/BibIX' },
  { id: 'refworks_tagged', label: 'RefWorks Tagged' },
  { id: 'ris', label: 'RIS' },
  { id: 'evernote', label: 'Simple Evernote Export' },
  { id: 'tei', label: 'TEI' },
  { id: 'rdf_dc', label: 'Unqualified Dublin Core RDF' },
  { id: 'wikipedia', label: 'Wikipedia Citation Templates' },
  { id: 'rdf_zotero', label: 'Zotero RDF' },
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
 * Item types a bibliography has no entry for.
 *
 * A note is not a work, an attachment is a file belonging to one, and an
 * annotation belongs to the attachment. Most of the formats leave them out —
 * the exceptions are Zotero RDF, which is a library export rather than a
 * bibliography, and COinS — so the interface does not offer an export that
 * would usually come back empty. It is what the client does too, by hiding
 * every format but its note translators when a selection is nothing but notes.
 */
const UNCITED = new Set(['note', 'attachment', 'annotation'])

export function exportable(itemType: string): boolean {
  return !UNCITED.has(itemType)
}
