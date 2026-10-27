/**
 * What the note editor's keys and menus do, as ProseMirror commands.
 *
 * Ported from zotero/note-editor at `acec74d`: `src/core/commands.js`, the
 * clearing of formats from `plugins/menu.js`, and the colour commands the
 * colour menus run. Typing the same keys here and on the desktop should leave
 * the same document behind, so the commands are the original's rather than
 * Tiptap's look-alikes, whose lists and indents behave differently.
 */
import { findParentNode, getMarkRange } from '@tiptap/core'
import { setBlockType } from '@tiptap/pm/commands'
import { Fragment, type MarkType, type Node as ProseMirrorNode, type NodeType } from '@tiptap/pm/model'
import { liftListItem, sinkListItem, wrapInList } from '@tiptap/pm/schema-list'
import { type Command, type EditorState, NodeSelection, TextSelection } from '@tiptap/pm/state'
import { canSplit } from '@tiptap/pm/transform'

import { MAX_INDENT } from './nodes'

function getClosestListItemNode(state: EditorState): ProseMirrorNode | undefined {
  const { $from } = state.selection
  for (let depth = $from.depth; depth > 0; depth--) {
    const node = $from.node(depth)
    if (node.type === state.schema.nodes.listItem) {
      return node
    }
  }
  return undefined
}

/** Tab and Shift-Tab: a list item moves a level, anything else is indented. */
export function changeIndent(dir: 1 | -1): Command {
  return (state, dispatch) => {
    const { $from, $to } = state.selection
    const listItem = state.schema.nodes.listItem!
    if (getClosestListItemNode(state)) {
      if (dir > 0) {
        sinkListItem(listItem)(state, dispatch)
      } else {
        liftListItem(listItem)(state, dispatch)
      }
      return true
    }

    const range = $from.blockRange($to)
    if (!range) return false
    let allSupportIndent = true
    const nodes: [number, ProseMirrorNode][] = []
    let pos = range.start + 1
    for (let i = range.startIndex; i < range.endIndex; i++) {
      const node = range.parent.child(i)
      nodes.push([pos, node])
      pos += node.nodeSize
      if (!node.type.spec.attrs?.indent) {
        allSupportIndent = false
      }
    }

    const { tr } = state
    if (allSupportIndent) {
      let changed = false
      for (const [pos, node] of nodes) {
        let indent: number | null = node.attrs.indent || 0
        if (dir === 1 ? indent! < MAX_INDENT : indent! >= 1) {
          indent! += dir
          if (indent === 0) {
            indent = null
          }
          tr.setBlockType(pos, pos, node.type, { ...node.attrs, indent })
          changed = true
        }
      }
      if (changed) {
        dispatch?.(tr)
        return true
      }
    }
    return false
  }
}

/** Backspace at the very start of an indented block takes the indent away. */
export const removeBlockIndent: Command = (state, dispatch) => {
  const { $from, $to } = state.selection
  const range = $from.blockRange($to)
  if (range && range.startIndex + 1 === range.endIndex) {
    const node = range.parent.child(range.startIndex)
    const pos = range.start + 1
    if (node.type.spec.attrs?.indent && node.attrs.indent !== null && pos === $from.pos) {
      dispatch?.(state.tr.setBlockType(pos, pos, node.type, { ...node.attrs, indent: null }))
      return true
    }
  }
  return false
}

export function hasAttr(state: EditorState, attr: string, value: unknown): boolean {
  let found = false
  state.doc.nodesBetween(state.selection.from, state.selection.to, node => {
    if (node.attrs[attr] === value) {
      found = true
    }
  })
  return found
}

/** Aligning text already aligned that way takes the alignment off again. */
export function toggleAlignment(direction: string | null): Command {
  return (state, dispatch) => {
    const { tr } = state
    let changes = false
    state.doc.nodesBetween(state.selection.from, state.selection.to, (node, pos) => {
      if (node.type.spec.attrs?.align) {
        changes = true
        if (node.attrs.align === direction) direction = null
        tr.setNodeMarkup(pos, null, { ...node.attrs, align: direction })
      }
    })
    if (!changes) return false
    dispatch?.(tr)
    return true
  }
}

function isList(node: ProseMirrorNode): boolean {
  const { bulletList, orderedList } = node.type.schema.nodes
  return node.type === bulletList || node.type === orderedList
}

/**
 * A list of the kind asked for: out of it if already in one, the other kind
 * turned into this one, and anything else wrapped.
 */
export function toggleList(listType: NodeType, itemType: NodeType): Command {
  return (state, dispatch, view) => {
    const { schema, selection } = state
    const range = selection.$from.blockRange(selection.$to)
    if (!range) {
      return false
    }

    const parentList = findParentNode(isList)(selection)

    if (range.depth >= 1 && parentList && range.depth - parentList.depth <= 1) {
      if (parentList.node.type === listType) {
        return liftListItem(itemType)(state, dispatch, view)
      }

      if (isList(parentList.node) && listType.validContent(parentList.node.content)) {
        dispatch?.(state.tr.setNodeMarkup(parentList.pos, listType))
        return false
      }
    }

    // The original runs this on the view and reads its state back, so the
    // wrap sees the paragraph; with no view the two steps cannot be chained.
    if (!view) return false
    setBlockType(schema.nodes.paragraph!)(state, dispatch)
    return wrapInList(listType)(view.state, dispatch)
  }
}

/**
 * A block type from the Format menu: choosing the one the cursor is already
 * in turns it back into a paragraph.
 */
export function toggleBlock(nodeType: NodeType, attrs: Record<string, unknown> = {}): Command {
  return (state, dispatch) => {
    const active = blockIsActive(state, nodeType, attrs)
    const command = active
      ? setBlockType(state.schema.nodes.paragraph!, attrs)
      : setBlockType(nodeType, attrs)
    return command(state, dispatch)
  }
}

function hasMarkup(node: ProseMirrorNode, type: NodeType, attrs: Record<string, unknown>): boolean {
  return node.type === type && Object.entries(attrs).every(([key, value]) => node.attrs[key] === value)
}

export function blockIsActive(
  state: EditorState,
  nodeType: NodeType,
  attrs: Record<string, unknown> = {},
): boolean {
  const { selection } = state
  if (selection instanceof NodeSelection) {
    return hasMarkup(selection.node, nodeType, attrs)
  }
  return selection.to <= selection.$from.end() && hasMarkup(selection.$from.parent, nodeType, attrs)
}

/** A list is active when the selection's nearest list is of its kind. */
export function listIsActive(state: EditorState, listType: NodeType): boolean {
  const parentList = findParentNode(isList)(state.selection)
  return parentList?.node.type === listType
}

/** The original's `isBlockquoteActive`: every top-level block selected is a quote. */
export function blockquoteIsActive(state: EditorState): boolean {
  const { $from, $to } = state.selection
  if ($from.depth < 1) return false
  let active = true
  state.doc.nodesBetween($from.before(1), $to.after(1), (_, pos) => {
    if (state.doc.nodeAt(pos)!.type !== state.schema.nodes.blockquote) {
      active = false
    }
    return false
  })
  return active
}

/** Clear Formatting: character formats go, and headings become paragraphs. */
export const clearFormatting: Command = (state, dispatch) => {
  const { tr } = state
  const marks = ['strong', 'em', 'underline', 'strike', 'textColor', 'backgroundColor', 'code', 'subsup']
  for (const mark of marks) {
    const { from, to } = tr.selection
    const type = state.schema.marks[mark]
    if (type) {
      tr.removeMark(from, to, type)
    }
  }
  const heading = state.schema.nodes.heading
  const { $from, $to } = tr.selection
  tr.doc.nodesBetween($from.pos, $to.pos, (node, pos) => {
    if (node.type === heading) {
      tr.setNodeMarkup(pos, state.schema.nodes.paragraph)
      return false
    }
    return true
  })
  tr.setStoredMarks([])
  dispatch?.(tr)
  return true
}

/** The extent of a mark around an empty selection, as the colour menus use it. */
function markRangeAtCursor(state: EditorState, type: MarkType): { from: number; to: number } | null {
  const { $from, empty } = state.selection
  if (!empty) return null
  const mark = $from.parent.childAfter($from.parentOffset).node?.marks.find(mark => mark.type === type)
  return mark ? (getMarkRange($from, type, mark.attrs) ?? null) : null
}

/** A text or highlight colour put on the selection, or on the word in that colour. */
export function setColor(type: MarkType, color: string): Command {
  return (state, dispatch) => {
    const { tr, selection, doc } = state
    let { from, to } = selection
    const range = markRangeAtCursor(state, type)
    if (range) {
      ;({ from, to } = range)
    }
    if (doc.rangeHasMark(from, to, type)) {
      tr.removeMark(from, to, type)
    }
    tr.addStoredMark(type.create({ color }))
    if (to > from) {
      tr.addMark(from, to, type.create({ color }))
    }
    dispatch?.(tr)
    return true
  }
}

export function removeColor(type: MarkType): Command {
  return (state, dispatch) => {
    const { tr, selection } = state
    let { from, to } = selection
    const range = markRangeAtCursor(state, type)
    if (range) {
      ;({ from, to } = range)
    }
    tr.removeStoredMark(type)
    if (to > from) {
      tr.removeMark(from, to, type)
    }
    dispatch?.(tr)
    return true
  }
}

/**
 * Enter at the end of a block keeps its attributes (an indent, an alignment)
 * on the new one, which ProseMirror's `splitBlock` drops.
 */
export const customSplitBlock: Command = (state, dispatch) => {
  const { $from, $to } = state.selection
  if (state.selection instanceof NodeSelection && state.selection.node.isBlock) {
    if (!$from.parentOffset || !canSplit(state.doc, $from.pos)) return false
    dispatch?.(state.tr.split($from.pos).scrollIntoView())
    return true
  }

  if (!$from.parent.isBlock) return false

  if (dispatch) {
    const atEnd = $to.parentOffset === $to.parent.content.size
    const tr = state.tr
    if (state.selection instanceof TextSelection) tr.deleteSelection()
    const deflt =
      $from.depth === 0 ? null : $from.node(-1).contentMatchAt($from.indexAfter(-1)).defaultType
    let types: { type: NodeType; attrs?: Record<string, unknown> }[] | null =
      atEnd && deflt ? [{ type: deflt, attrs: $from.node().attrs }] : null
    let can = canSplit(tr.doc, $from.pos, 1, types ?? undefined)
    if (!types && !can && canSplit(tr.doc, tr.mapping.map($from.pos), 1, deflt ? [{ type: deflt }] : undefined)) {
      types = [{ type: deflt!, attrs: $from.node().attrs }]
      can = true
    }
    if (can) {
      tr.split(tr.mapping.map($from.pos), 1, types ?? undefined)
      if (
        !$from.parentOffset &&
        $from.parent.type !== deflt &&
        // The original passes `$from.parent` as a second argument, which
        // `Fragment.from` ignores.
        $from.node(-1).canReplace($from.index(-1), $from.indexAfter(-1), Fragment.from(deflt!.create()))
      ) {
        tr.setNodeMarkup(tr.mapping.map($from.before()), deflt)
      }
    }
    dispatch(tr.scrollIntoView())
  }
  return true
}
