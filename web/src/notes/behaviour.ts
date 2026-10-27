/**
 * How the note editor behaves when typed in: its keys, its input rules, and
 * the clean-up it does after every change.
 *
 * Ported from zotero/note-editor at `acec74d` (`src/core/keymap.js`,
 * `input-rules.js`, `history-commands.js` and `plugins/schema-transform.js`)
 * as ProseMirror plugins inside one Tiptap extension, so a key does here what
 * it does on the desktop. Tiptap's own keymap is switched off where the editor
 * is made, since it would answer Enter and Backspace first.
 *
 * Left out: the citation key (the browser cannot pick from the desktop's
 * library) and the maths rules and keys, which belong to the desktop's maths
 * editor; a note's maths is kept and shown as its TeX source.
 */
import { Extension } from '@tiptap/core'
import {
  baseKeymap,
  chainCommands,
  createParagraphNear,
  exitCode,
  joinDown,
  joinUp,
  lift,
  liftEmptyBlock,
  newlineInCode,
  setBlockType,
  toggleMark,
  wrapIn,
} from '@tiptap/pm/commands'
import { history, redo, undo } from '@tiptap/pm/history'
import {
  ellipsis,
  InputRule,
  inputRules,
  smartQuotes,
  textblockTypeInputRule,
  undoInputRule,
  wrappingInputRule,
} from '@tiptap/pm/inputrules'
import { keymap } from '@tiptap/pm/keymap'
import { Fragment, type MarkType, type Schema } from '@tiptap/pm/model'
import { splitListItem, wrapInList } from '@tiptap/pm/schema-list'
import { type Command, Plugin, TextSelection } from '@tiptap/pm/state'
import { goToNextCell, tableEditing } from '@tiptap/pm/tables'

import { changeIndent, customSplitBlock, removeBlockIndent } from './commands'
import { schemaTransform } from './html'

export const undoCommand = chainCommands(undoInputRule, undo)
export const redoCommand = redo

export interface BehaviourOptions {
  /** Mod-K: open the link editor for the selection. */
  toggleLink: () => boolean
  /** Alt-F10: move the keyboard to the toolbar. */
  focusToolbar: () => boolean
  /** Turn straight quotes into curly ones as they are typed, as Zotero's
   *  `note.smartQuotes` does by default. */
  smartQuotes: boolean
}

function buildKeymap(schema: Schema, options: BehaviourOptions): Record<string, Command> {
  const keys: Record<string, Command> = {}
  const bind = (key: string, cmd: Command) => {
    keys[key] = cmd
  }
  const { nodes, marks } = schema

  bind('Mod-z', undoCommand)
  bind('Shift-Mod-z', redoCommand)
  // Bound twice in the original, so that the second wins and Backspace does
  // not undo an input rule there; it does not here either.
  bind('Backspace', undoInputRule)
  bind('Backspace', removeBlockIndent)
  if (!/Mac|iP(hone|[oa]d)/.test(typeof navigator === 'undefined' ? '' : navigator.platform)) {
    bind('Ctrl-y', redoCommand)
  }

  bind('Alt-F10', () => options.focusToolbar())
  bind('Alt-ArrowUp', joinUp)
  bind('Alt-ArrowDown', joinDown)
  bind('Mod-BracketLeft', lift)

  bind('Mod-b', toggleMark(marks.strong!))
  bind('Mod-B', toggleMark(marks.strong!))
  bind('Mod-i', toggleMark(marks.em!))
  bind('Mod-I', toggleMark(marks.em!))
  bind('Mod-u', toggleMark(marks.underline!))
  bind('Mod-U', toggleMark(marks.underline!))
  bind('Mod-`', toggleMark(marks.code!))

  bind('Mod-k', () => options.toggleLink())
  bind('Mod-K', () => options.toggleLink())

  bind('Shift-Ctrl-8', wrapInList(nodes.bulletList!))
  bind('Shift-Ctrl-9', wrapInList(nodes.orderedList!))
  bind('Ctrl->', wrapIn(nodes.blockquote!))

  // Hard break
  const hardBreak = chainCommands(exitCode, (state, dispatch) => {
    dispatch?.(state.tr.replaceSelectionWith(nodes.hardBreak!.create()).scrollIntoView())
    return true
  })
  bind('Mod-Enter', hardBreak)
  bind('Shift-Enter', hardBreak)

  bind('Shift-Tab', chainCommands(goToNextCell(-1), changeIndent(-1)))
  bind('Tab', chainCommands(goToNextCell(1), changeIndent(1)))

  bind('Shift-Ctrl-0', setBlockType(nodes.paragraph!))
  bind('Shift-Ctrl-\\', setBlockType(nodes.codeBlock!))
  for (let level = 1; level <= 6; level++) {
    bind(`Shift-Ctrl-${level}`, setBlockType(nodes.heading!, { level }))
  }

  bind('Mod-_', (state, dispatch) => {
    dispatch?.(state.tr.replaceSelectionWith(nodes.horizontalRule!.create()).scrollIntoView())
    return true
  })

  bind(
    'Enter',
    chainCommands(
      splitListItem(nodes.listItem!),
      newlineInCode,
      createParagraphNear,
      liftEmptyBlock,
      customSplitBlock,
    ),
  )

  return keys
}

function markInputRule(regexp: RegExp, markType: MarkType, size: number): InputRule {
  return new InputRule(regexp, (state, match, start, end) => {
    const to = end
    const from = match[1] ? to - match[1].length + 1 : start
    const code = markType.schema.marks.code
    if (code && code.isInSet(state.doc.resolve(from + 1).marks())) {
      return null
    }

    // Skip input rule if matched range includes inline math node
    let math = false
    state.doc.nodesBetween(from, to, node => {
      if (node.type.name === 'math_inline') math = true
    })
    if (math) {
      return null
    }

    let tr = state.tr.addMark(from, to, markType.create())
    if (size > 1) {
      tr = tr.delete(to - (size - 1), to)
    }
    return tr.delete(from, from + size).removeStoredMark(markType)
  })
}

function linkInputRule(schema: Schema): InputRule {
  return new InputRule(/(^|[^!])\[(.*?)\]\((\S+)\)$/, (state, match, start, end) =>
    state.tr.replaceWith(
      start + match[1]!.length,
      end,
      schema.text(match[2]!, [schema.mark('link', { href: match[3] })]),
    ),
  )
}

function buildInputRules(schema: Schema, options: BehaviourOptions): Plugin {
  const { nodes, marks } = schema
  let rules = [
    ellipsis,
    wrappingInputRule(/^\s*>\s$/, nodes.blockquote!),
    wrappingInputRule(/^\s*(1\.)\s$/, nodes.orderedList!),
    wrappingInputRule(/^\s*([-+*])\s$/, nodes.bulletList!),
    new InputRule(/^```$/, (state, _, start, end) => {
      const { tr } = state
      return tr
        .replaceWith(start - 1, end, Fragment.from(nodes.codeBlock!.create()))
        .setSelection(new TextSelection(tr.doc.resolve(start)))
    }),
    linkInputRule(schema),
    markInputRule(/(?:[^`0-9A-Za-z]+)(__([^\s_][^_]+)__)$|^(__([^\s _][^_]+)__)$/, marks.strong!, 2),
    markInputRule(/^(?:[^`]+)(\*\*([^\s*][^*]+)\*\*)$|^(\*\*([^\s*][^*]+)\*\*)$/, marks.strong!, 2),
    markInputRule(/(?:[^_`0-9A-Za-z]+)(_([^\s_][^_]+?)_)$|^(_([^\s_][^_]+)_)$/, marks.em!, 1),
    markInputRule(/^(?:[^*`]+)(\*([^\s*][^*]+?)\*)$|^(\*([^\s*][^*]+)\*)$/, marks.em!, 1),
    markInputRule(/^(?:[^`]+)(~~([^\s~][^~]+)~~)$|^(~~([^\s~][^~]+)~~)$/, marks.strike!, 2),
    markInputRule(/(`[^\s`].*`)$/, marks.code!, 1),
    new InputRule(/^---$|^\*\*\*$/, (state, _, start, end) =>
      state.tr.replaceWith(start - 1, end, Fragment.from(nodes.horizontalRule!.create())),
    ),
    textblockTypeInputRule(/^(#{1,6}) $/, nodes.heading!, match => ({ level: match[1]!.length })),
  ]
  if (options.smartQuotes) {
    rules = [...smartQuotes, ...rules]
  }
  return inputRules({ rules })
}

export const NoteBehaviour = Extension.create<BehaviourOptions>({
  name: 'noteBehaviour',

  addOptions() {
    return { toggleLink: () => false, focusToolbar: () => false, smartQuotes: true }
  },

  addProseMirrorPlugins() {
    const { schema } = this.editor
    return [
      new Plugin({
        appendTransaction: (_, __, newState) => schemaTransform(newState),
      }),
      buildInputRules(schema, this.options),
      keymap(buildKeymap(schema, this.options)),
      keymap(baseKeymap),
      tableEditing(),
      history(),
    ]
  },
})
