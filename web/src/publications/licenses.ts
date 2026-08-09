/**
 * The licences My Publications offers, as the server holds them.
 *
 * The same table as `services/publications.py`, and `tests/test_web_publications.py`
 * fails if the two drift apart. It has to be here as well as there: the wizard
 * shows the name before the item is written, and the server writes it into the
 * `rights` field afterwards, so a name that differed between them would promise
 * one licence and store another.
 *
 * The names are not translated. Zotero's are — its German catalogue writes
 * "Creative Commons Namensnennung 4.0 Internationale Lizenz" into the field —
 * but Rights is data rather than a label: it is exported and cited, and it is
 * read by clients that have nothing to do with the language this account
 * happens to read in. Showing the English name here is showing what the item
 * will say, which is worth more than a translated label above a stored string
 * that differs from it.
 */

export interface License {
  /** What the browser sends, and what the server looks up. */
  id: string
  /** What goes into the item's Rights field. */
  name: string
  /** Where the licence itself is published, or `null` for reserved rights. */
  url: string | null
}

export const LICENSES: License[] = [
  { id: 'reserved', name: 'All rights reserved', url: null },
  {
    id: 'cc-by',
    name: 'Creative Commons Attribution 4.0 International License',
    url: 'https://creativecommons.org/licenses/by/4.0/',
  },
  {
    id: 'cc-by-sa',
    name: 'Creative Commons Attribution-ShareAlike 4.0 International License',
    url: 'https://creativecommons.org/licenses/by-sa/4.0/',
  },
  {
    id: 'cc-by-nd',
    name: 'Creative Commons Attribution-NoDerivatives 4.0 International License',
    url: 'https://creativecommons.org/licenses/by-nd/4.0/',
  },
  {
    id: 'cc-by-nc',
    name: 'Creative Commons Attribution-NonCommercial 4.0 International License',
    url: 'https://creativecommons.org/licenses/by-nc/4.0/',
  },
  {
    id: 'cc-by-nc-sa',
    name: 'Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License',
    url: 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
  },
  {
    id: 'cc-by-nc-nd',
    name: 'Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License',
    url: 'https://creativecommons.org/licenses/by-nc-nd/4.0/',
  },
  {
    id: 'cc0',
    name: 'CC0 1.0 Universal Public Domain Dedication',
    url: 'https://creativecommons.org/publicdomain/zero/1.0/',
  },
]

/**
 * The licence the two questions on the last page arrive at.
 *
 * `getLicense` in the client's `publicationsDialog.js`: attribution always,
 * then non-commercial, then either no derivatives or share-alike — which is
 * why "no adaptations" and "share alike" are one question with three answers
 * rather than two checkboxes that can contradict each other.
 */
export function creativeCommonsLicense(
  adaptations: 'yes' | 'no' | 'sharealike',
  commercial: 'yes' | 'no',
): string {
  let id = 'cc-by'
  if (commercial === 'no') id += '-nc'
  if (adaptations === 'no') id += '-nd'
  else if (adaptations === 'sharealike') id += '-sa'
  return id
}

export function licenseFor(id: string): License | undefined {
  return LICENSES.find((entry) => entry.id === id)
}

/**
 * The short name a Creative Commons licence is known by: CC BY, CC BY-NC-SA.
 *
 * Derived from the identifier rather than kept in the table beside the full
 * name, because it *is* the identifier — spelt the way the licence spells it.
 * Two columns saying the same thing are two columns that can disagree.
 *
 * Null for reserved rights, which is not a licence and has no code. Zotero
 * shows the badge image here; this interface has no images to show, and the
 * code is what the badge says anyway.
 */
export function licenseCode(id: string): string | null {
  if (id === 'reserved') return null
  if (id === 'cc0') return 'CC0'
  return id.toUpperCase().replace('-', ' ')
}
