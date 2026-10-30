/** Automatic block direction belongs to the view, never the synced note HTML. */
import { Extension } from '@tiptap/core'
import type { Node } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

const key = new PluginKey<DecorationSet>('noteDirection')

function directions(doc: Node): DecorationSet {
  const decorations: Decoration[] = []
  const visit = (node: Node, position: number, explicit: boolean) => {
    const directed = explicit || node.attrs.dir === 'ltr' || node.attrs.dir === 'rtl'
    if (!directed && (node.isTextblock || ['bulletList', 'orderedList', 'blockquote'].includes(node.type.name))) {
      decorations.push(Decoration.node(position, position + node.nodeSize, { dir: 'auto' }))
    }
    node.forEach((child, offset) => visit(child, position + 1 + offset, directed))
  }
  doc.forEach((node, offset) => visit(node, offset, false))
  return DecorationSet.create(doc, decorations)
}

export const NoteDirection = Extension.create({
  name: 'noteDirection',
  addProseMirrorPlugins() {
    return [new Plugin<DecorationSet>({
      key,
      state: {
        init: (_, state) => directions(state.doc),
        apply: (transaction, previous) => transaction.docChanged ? directions(transaction.doc) : previous,
      },
      props: { decorations: state => key.getState(state) },
    })]
  },
})
