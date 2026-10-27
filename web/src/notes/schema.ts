/**
 * Zotero's note schema as Tiptap extensions.
 *
 * `nodes.ts` and `marks.ts` hold the note editor's specs as plain ProseMirror;
 * this turns each into a Tiptap extension of the same name, in the same order,
 * whose parse rules and rendering are the spec's own. Order matters twice
 * over: parse rules are tried in schema order (`pre.math` before `pre`), and
 * marks nest in it when written out (`<strong><em>`, never `<em><strong>`).
 *
 * Tiptap reads each attribute off an element by its name unless told
 * otherwise, which would let a stray `align="center"` override what the
 * original's `getAttrs` made of the element's style. Each attribute is
 * therefore declared with a `parseHTML` that reads nothing, leaving the rule's
 * own `getAttrs` the whole say, and as not `rendered`, since every `toDOM`
 * here writes its own attributes.
 */
import {
  type AnyExtension,
  type Attributes,
  getSchema,
  Mark,
  Node,
  type NodeConfig,
} from '@tiptap/core'
import type { AttributeSpec, MarkSpec, NodeSpec, Schema } from '@tiptap/pm/model'

import { marks } from './marks'
import { nodes } from './nodes'

function attributes(specs: Record<string, AttributeSpec> | undefined): Attributes {
  return Object.fromEntries(
    Object.entries(specs ?? {}).map(([name, spec]) => [
      name,
      {
        default: spec.default,
        isRequired: !('default' in spec),
        validate: spec.validate,
        rendered: false,
        parseHTML: () => null,
      },
    ]),
  )
}

const NODE_FIELDS = [
  'content',
  'marks',
  'group',
  'inline',
  'atom',
  'selectable',
  'draggable',
  'code',
  'defining',
  'isolating',
] as const

function nodeExtension(name: string, spec: NodeSpec): AnyExtension {
  const config: Partial<NodeConfig> = {
    name,
    topNode: name === 'doc',
    addAttributes: () => attributes(spec.attrs),
  }
  for (const field of NODE_FIELDS) {
    if (spec[field] !== undefined) {
      ;(config as Record<string, unknown>)[field] = spec[field]
    }
  }
  if (spec.parseDOM) {
    const rules = spec.parseDOM
    config.parseHTML = () => rules as any
  }
  if (spec.toDOM) {
    const toDOM = spec.toDOM
    config.renderHTML = ({ node }) => toDOM(node)
  }
  if (spec.tableRole) {
    const tableRole = spec.tableRole
    // Called for every node in the schema, hence the name check.
    config.extendNodeSchema = extension => (extension.name === name ? { tableRole } : {})
  }
  return Node.create(config)
}

function markExtension(name: string, spec: MarkSpec): AnyExtension {
  const toDOM = spec.toDOM!
  const rules = spec.parseDOM ?? []
  return Mark.create({
    name,
    inclusive: spec.inclusive,
    excludes: spec.excludes,
    addAttributes: () => attributes(spec.attrs),
    parseHTML: () => rules as any,
    renderHTML: ({ mark }) => toDOM(mark, true),
  })
}

/** The schema's nodes and marks; an editor adds its behaviour beside them. */
export function noteSchemaExtensions(): AnyExtension[] {
  return [
    ...Object.entries(nodes).map(([name, spec]) => nodeExtension(name, spec)),
    ...Object.entries(marks).map(([name, spec]) => markExtension(name, spec)),
  ]
}

/** A schema for reading and writing notes outside an editor. */
export function noteSchema(): Schema {
  return getSchema(noteSchemaExtensions())
}
