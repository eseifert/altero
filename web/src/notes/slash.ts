/**
 * The "/" menu: typing a slash at the start of a line or after a space offers
 * the block types, narrowed by what is typed after it, as Notion and Linear
 * do. This is the part that watches the text; `NoteSlashMenu.vue` draws the
 * list and decides what a key does while it is open.
 *
 * It opens only on typing, never on moving the cursor into a slash written
 * earlier, and once Escape has closed it, it stays closed for that slash.
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'

export interface SlashQuery {
  /** Where the slash is. */
  from: number
  /** Where the cursor is, after what was typed. */
  to: number
  query: string
}

interface SlashState {
  active: SlashQuery | null
  /** The slash Escape closed the menu on, mapped through later changes. */
  dismissed: number | null
}

export const slashKey = new PluginKey<SlashState>('noteSlash')

/** A slash at the start of a line or after a space, then up to 24 letters. */
const TRIGGER = /(?:^|\s)\/([^\s/]{0,24})$/u

export interface SlashOptions {
  onChange: (query: SlashQuery | null, view: EditorView) => void
  /** A key pressed while the menu is open; true if the menu took it. */
  onKeyDown: (event: KeyboardEvent) => boolean
}

/** Closes the menu and leaves the slash as typed. */
export function dismissSlash(view: EditorView): void {
  view.dispatch(view.state.tr.setMeta(slashKey, 'dismiss'))
}

export const SlashCommands = Extension.create<SlashOptions>({
  name: 'noteSlash',
  // Before the note editor's own keys, which would take Enter for a new line.
  priority: 1000,

  addOptions() {
    return { onChange: () => {}, onKeyDown: () => false }
  },

  addProseMirrorPlugins() {
    const options = this.options
    return [
      new Plugin<SlashState>({
        key: slashKey,
        state: {
          init: () => ({ active: null, dismissed: null }),
          apply(tr, previous, _, state) {
            let dismissed = previous.dismissed === null ? null : tr.mapping.map(previous.dismissed)
            if (tr.getMeta(slashKey) === 'dismiss') {
              return { active: null, dismissed: previous.active?.from ?? dismissed }
            }
            const { selection } = state
            if (!selection.empty) return { active: null, dismissed }
            const { $from } = selection
            if (!$from.parent.isTextblock || $from.parent.type.spec.code) return { active: null, dismissed }
            const before = $from.parent.textBetween(0, $from.parentOffset, undefined, '￼')
            const match = TRIGGER.exec(before)
            if (!match) return { active: null, dismissed: null }
            const query = match[1]!
            const to = $from.pos
            const from = to - query.length - 1
            if (from === dismissed) return { active: null, dismissed }
            if (!previous.active && !tr.docChanged) return { active: null, dismissed }
            return { active: { from, to, query }, dismissed }
          },
        },
        view: () => ({
          update: view => options.onChange(slashKey.getState(view.state)?.active ?? null, view),
          destroy: () => {},
        }),
        props: {
          handleKeyDown: (view, event) =>
            slashKey.getState(view.state)?.active ? options.onKeyDown(event) : false,
        },
      }),
    ]
  },
})
