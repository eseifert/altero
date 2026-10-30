/**
 * Cleaning HTML that somebody else wrote before it is put on a page.
 *
 * Two kinds reach `v-html`: a note, which is whatever HTML a client or a group
 * member synced, and a rendered bibliography, which the server builds from item
 * fields. Both are shown on public pages too — a shared collection and a profile —
 * so a handler or a script in either would run for anybody who opened the link.
 * The server stores a note exactly as it was sent, since the v3 API round-trips
 * it to every client; cleaning happens here, where it is displayed.
 *
 * Beyond DOMPurify's own rules (no script, no handlers, no `javascript:` URL),
 * a note keeps only what Zotero's note editor writes: no form to type a
 * password into, no frame, no stylesheet, and no class or style that could
 * borrow this interface's own and lay something over it.
 */
import DOMPurify from 'dompurify'

interface Policy {
  /** The classes an element may carry; every other class is dropped. */
  classes: ReadonlySet<string>
  /** The style properties an element may set; every other one is dropped. */
  styles: ReadonlySet<string>
}

/** The classes Zotero's note editor gives citations, annotations and maths. */
const NOTE: Policy = {
  classes: new Set(['citation', 'highlight', 'underline', 'math']),
  styles: new Set([
    'color',
    'background-color',
    'text-align',
    'text-decoration',
    'font-weight',
    'font-style',
    'padding-left',
    'padding-right',
    'padding-inline-start',
    'padding-inline-end',
  ]),
}

/** What the server's CSL renderer wraps a bibliography in. */
const BIBLIOGRAPHY: Policy = {
  classes: new Set([
    'csl-bib-body',
    'csl-entry',
    'csl-left-margin',
    'csl-right-inline',
    'csl-indent',
    'csl-block',
  ]),
  styles: new Set([
    'line-height',
    'padding-left',
    'text-indent',
    'margin-bottom',
    'font-variant',
    'font-style',
    'font-weight',
    'text-decoration',
    'vertical-align',
  ]),
}

/** Elements that have no place in a note whatever DOMPurify thinks of them. */
const FORBID_TAGS = [
  'style',
  'form',
  'input',
  'button',
  'textarea',
  'select',
  'option',
  'label',
  'fieldset',
  'dialog',
  'template',
]

/** A value with no function in it but a colour. No `url()`, no `var()`. */
const PLAIN_VALUE = /^[\w\s#%.,+-]*$/
const COLOR_FUNCTION = /^(?:rgba?|hsla?)\([\d\s.,%/]+\)$/i

const TEXT_BLOCKS = new Set(['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'UL', 'OL', 'BLOCKQUOTE', 'PRE', 'TD', 'TH'])

/** A stored direction wins, including one set on a surrounding list or quote. */
function explicitlyDirected(node: Element): boolean {
  for (let current: Element | null = node; current; current = current.parentElement) {
    if (['ltr', 'rtl'].includes(current.getAttribute('dir')?.toLowerCase() ?? '')) return true
  }
  return false
}

function keepStyles(value: string, allowed: ReadonlySet<string>): string {
  const kept: string[] = []
  for (const declaration of value.split(';')) {
    const colon = declaration.indexOf(':')
    if (colon < 0) continue
    const name = declaration.slice(0, colon).trim().toLowerCase()
    const setting = declaration.slice(colon + 1).trim()
    if (!allowed.has(name) || !setting) continue
    if (PLAIN_VALUE.test(setting) || COLOR_FUNCTION.test(setting)) kept.push(`${name}: ${setting}`)
  }
  return kept.join('; ')
}

function cleaner(policy: Policy): (html: string | null | undefined) => string {
  const purify = DOMPurify(window)
  purify.addHook('uponSanitizeAttribute', (_node, data) => {
    if (data.attrName === 'class') {
      data.attrValue = data.attrValue
        .split(/\s+/)
        .filter((name) => policy.classes.has(name))
        .join(' ')
    } else if (data.attrName === 'style') {
      data.attrValue = keepStyles(data.attrValue, policy.styles)
    } else {
      return
    }
    if (!data.attrValue) data.keepAttr = false
  })
  // A link leaves the page rather than replacing it, and tells its target
  // neither where it came from nor how to reach back.
  purify.addHook('afterSanitizeAttributes', (node) => {
    if ((TEXT_BLOCKS.has(node.tagName) || node.classList.contains('csl-entry')) && !explicitlyDirected(node)) {
      node.setAttribute('dir', 'auto')
    }
    if (node.tagName === 'A' && node.hasAttribute('href')) {
      node.setAttribute('target', '_blank')
      node.setAttribute('rel', 'noopener noreferrer')
    }
  })
  return (html) =>
    html
      ? purify.sanitize(html, {
          USE_PROFILES: { html: true },
          FORBID_TAGS,
          SANITIZE_NAMED_PROPS: true,
        })
      : ''
}

/** A note's HTML, safe to display, with automatic direction per undirected block. */
export const cleanNote = cleaner(NOTE)

/** A rendered bibliography or citation, safe to put on a page. */
export const cleanBibliography = cleaner(BIBLIOGRAPHY)
