/**
 * What the note editor's tools show and do, for whichever bar draws them.
 *
 * A note is formatted from two places: the bar that floats over selected text
 * where there is a mouse, and the row docked on the keyboard where there is a
 * finger. Both read the same state and run the same commands, and both name
 * things in Zotero's words, so this holds that once. Each value is read again
 * after every transaction, which `tick` stands for.
 */
import type { Editor } from '@tiptap/vue-3'
import { lift, wrapIn } from '@tiptap/pm/commands'
import type { Command } from '@tiptap/pm/state'
import { computed, nextTick, ref, type ShallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NoteMenuEntry } from '@/components/NoteMenu.vue'

import { redoCommand, undoCommand } from './behaviour'
import {
  blockIsActive,
  blockquoteIsActive,
  changeIndent,
  clearFormatting,
  hasAttr,
  listIsActive,
  removeColor,
  setColor,
  toggleAlignment,
  toggleBlock,
  toggleList,
} from './commands'
import { safeHref } from './editor'
import { HIGHLIGHT_COLORS, TEXT_COLORS } from './marks'

export type BlockId =
  | 'paragraph'
  | 'heading1'
  | 'heading2'
  | 'heading3'
  | 'codeBlock'
  | 'bulletList'
  | 'orderedList'
  | 'blockquote'

export function useNoteFormatting(editor: ShallowRef<Editor>) {
  const { t } = useI18n()

  /** Bumped on every transaction, so what the tools show is read again. */
  const tick = ref(0)
  editor.value.on('transaction', () => tick.value++)

  const schema = computed(() => editor.value.schema)

  function run(command: Command): void {
    const { view } = editor.value
    command(view.state, view.dispatch, view)
    view.focus()
  }

  function markActive(name: string, attrs: Record<string, unknown> = {}): boolean {
    void tick.value
    return editor.value.isActive(name, attrs)
  }

  function toggleMark(name: string, attrs?: Record<string, unknown>): void {
    editor.value.chain().focus().toggleMark(name, attrs).run()
  }

  /* ---- Block types: the Format menu, the floating bar's first menu, and "/". ---- */

  const blockLabels = computed<Record<BlockId, string>>(() => ({
    paragraph: t('Paragraph'),
    heading1: t('Heading 1'),
    heading2: t('Heading 2'),
    heading3: t('Heading 3'),
    codeBlock: t('Monospaced'),
    bulletList: t('Bulleted List'),
    orderedList: t('Numbered List'),
    blockquote: t('Block Quote'),
  }))

  const SAMPLES: Partial<Record<BlockId, string>> = { heading1: 'h1', heading2: 'h2', heading3: 'h3', codeBlock: 'code' }

  /** Which block type the cursor is in, as the desktop's menu marks it. */
  const activeBlocks = computed<Record<BlockId, boolean>>(() => {
    void tick.value
    const { state } = editor.value
    const nodes = schema.value.nodes
    const inList = listIsActive(state, nodes.bulletList!) || listIsActive(state, nodes.orderedList!)
    const inQuote = blockquoteIsActive(state)
    return {
      paragraph: blockIsActive(state, nodes.paragraph!) && !inList && !inQuote,
      heading1: blockIsActive(state, nodes.heading!, { level: 1 }),
      heading2: blockIsActive(state, nodes.heading!, { level: 2 }),
      heading3: blockIsActive(state, nodes.heading!, { level: 3 }),
      codeBlock: blockIsActive(state, nodes.codeBlock!),
      bulletList: listIsActive(state, nodes.bulletList!),
      orderedList: listIsActive(state, nodes.orderedList!),
      blockquote: inQuote,
    }
  })

  /** The name of the block the cursor is in, for the floating bar's menu. */
  const currentBlock = computed(() => {
    const active = (Object.keys(activeBlocks.value) as BlockId[]).filter(id => activeBlocks.value[id])
    const shown = active.find(id => id !== 'paragraph') ?? active[0] ?? 'paragraph'
    return blockLabels.value[shown]
  })

  const blockEntries = computed<NoteMenuEntry[]>(() =>
    (Object.keys(blockLabels.value) as BlockId[]).map(id => ({
      id,
      label: blockLabels.value[id],
      kind: 'radio' as const,
      checked: activeBlocks.value[id],
      sample: SAMPLES[id],
    })),
  )

  function blockCommand(id: BlockId): Command {
    const nodes = schema.value.nodes
    const commands: Record<BlockId, Command> = {
      paragraph: toggleBlock(nodes.paragraph!),
      heading1: toggleBlock(nodes.heading!, { level: 1 }),
      heading2: toggleBlock(nodes.heading!, { level: 2 }),
      heading3: toggleBlock(nodes.heading!, { level: 3 }),
      codeBlock: toggleBlock(nodes.codeBlock!),
      bulletList: toggleList(nodes.bulletList!, nodes.listItem!),
      orderedList: toggleList(nodes.orderedList!, nodes.listItem!),
      blockquote: (state, dispatch, view) =>
        blockquoteIsActive(state) ? lift(state, dispatch) : wrapIn(nodes.blockquote!)(state, dispatch, view),
    }
    return commands[id]
  }

  /* ---- Character formats. ---- */

  const MARKS: Record<string, [string, Record<string, unknown>?]> = {
    strong: ['strong'],
    em: ['em'],
    underline: ['underline'],
    strike: ['strike'],
    sub: ['subsup', { type: 'sub' }],
    sup: ['subsup', { type: 'sup' }],
    code: ['code'],
  }

  function markIsOn(id: string): boolean {
    const [name, attrs] = MARKS[id]!
    return markActive(name, attrs)
  }

  const markLabels = computed<Record<string, string>>(() => ({
    strong: t('Bold'),
    em: t('Italic'),
    underline: t('Underline'),
    strike: t('Strikethrough'),
    sub: t('Subscript'),
    sup: t('Superscript'),
    code: t('Monospaced'),
  }))

  function markEntries(ids: string[], separated = false): NoteMenuEntry[] {
    void tick.value
    const samples: Record<string, string> = { underline: 'underline', strike: 'strike', code: 'code' }
    return ids.map((id, index) => ({
      id,
      label: markLabels.value[id]!,
      kind: 'check' as const,
      checked: markIsOn(id),
      sample: samples[id],
      separated: separated && index === 0,
    }))
  }

  /** Everything the desktop's Format menu holds: blocks, then formats. */
  const formatEntries = computed<NoteMenuEntry[]>(() => [
    ...blockEntries.value,
    ...markEntries(['underline', 'strike', 'sub', 'sup', 'code'], true),
  ])

  /** The menu itself: a block type by its id, a format by its own. */
  function format(id: string): void {
    if (id in MARKS) {
      const [name, attrs] = MARKS[id]!
      toggleMark(name, attrs)
    } else {
      run(blockCommand(id as BlockId))
    }
  }

  /* ---- Colours. ---- */

  /** The names of the note editor's colours, Zotero's `general-<colour>`. */
  function colorName(name: string): string {
    const names: Record<string, string> = {
      red: t('Red'),
      orange: t('Orange'),
      yellow: t('Yellow'),
      green: t('Green'),
      purple: t('Purple'),
      magenta: t('Magenta'),
      blue: t('Blue'),
      gray: t('Gray'),
    }
    return names[name] ?? name
  }

  function colorEntries(markName: string, colors: readonly (readonly [string, string])[]): NoteMenuEntry[] {
    void tick.value
    const current = String(editor.value.getAttributes(markName).color ?? '').toLowerCase()
    return [
      { id: '', label: t('Remove Color'), kind: 'action' },
      ...colors.map(([name, code]) => ({
        id: code,
        label: colorName(name),
        kind: 'radio' as const,
        swatch: code,
        checked: current === code,
        separated: name === 'red',
      })),
    ]
  }

  const textColors = computed(() => colorEntries('textColor', TEXT_COLORS))
  const highlightColors = computed(() => colorEntries('backgroundColor', HIGHLIGHT_COLORS))

  /** The colour each colour button last put on text, for its bar. */
  const lastText = ref<string | null>(null)
  const lastHighlight = ref<string | null>(null)

  function color(markName: 'textColor' | 'backgroundColor', code: string): void {
    const type = schema.value.marks[markName]!
    if (code) {
      run(setColor(type, code))
      if (markName === 'textColor') lastText.value = code
      else lastHighlight.value = code
    } else {
      run(removeColor(type))
    }
  }

  /* ---- Alignment and indent. ---- */

  const alignEntries = computed<NoteMenuEntry[]>(() => {
    void tick.value
    const { state } = editor.value
    return [
      { id: 'left', label: t('Align Left'), kind: 'radio', checked: hasAttr(state, 'align', 'left') },
      { id: 'center', label: t('Align Center'), kind: 'radio', checked: hasAttr(state, 'align', 'center') },
      { id: 'right', label: t('Align Right'), kind: 'radio', checked: hasAttr(state, 'align', 'right') },
      { id: 'outdent', label: t('Decrease Indent'), kind: 'action', separated: true },
      { id: 'indent', label: t('Increase Indent'), kind: 'action' },
    ]
  })

  function align(id: string): void {
    if (id === 'indent') run(changeIndent(1))
    else if (id === 'outdent') run(changeIndent(-1))
    else run(toggleAlignment(id))
  }

  /* ---- Links. ---- */

  const linkEditing = ref(false)
  const linkDraft = ref('')

  /** The address of the link the cursor is in, if any. */
  const currentLink = computed<string | null>(() => {
    void tick.value
    return markActive('link') ? (editor.value.getAttributes('link').href ?? null) : null
  })

  async function openLink(): Promise<void> {
    if (!editor.value.isEditable) return
    linkDraft.value = currentLink.value ?? ''
    linkEditing.value = true
    await nextTick()
  }

  /** What was typed, as an address: one with no scheme is taken to be a web page. */
  function address(typed: string): string {
    const value = typed.trim()
    return /^[a-z][a-z\d+.-]*:/i.test(value) ? value : `https://${value}`
  }

  function applyLink(): void {
    const value = linkDraft.value.trim()
    linkEditing.value = false
    const chain = editor.value.chain().focus()
    if (!value) {
      chain.extendMarkRange('link').unsetMark('link').run()
      return
    }
    const href = address(value)
    const { empty } = editor.value.state.selection
    if (empty && !currentLink.value) {
      chain.insertContent({ type: 'text', text: value, marks: [{ type: 'link', attrs: { href } }] }).run()
    } else {
      chain.extendMarkRange('link').setMark('link', { href }).run()
    }
  }

  function cancelLink(): void {
    linkEditing.value = false
    editor.value.commands.focus()
  }

  function unlink(): void {
    editor.value.chain().focus().extendMarkRange('link').unsetMark('link').run()
  }

  function followLink(): void {
    const href = safeHref(currentLink.value)
    if (href) window.open(href, '_blank', 'noopener,noreferrer')
  }

  return {
    tick,
    run,
    markActive,
    toggleMark,
    markIsOn,
    markLabels,
    markEntries,
    blockLabels,
    blockEntries,
    blockCommand,
    currentBlock,
    formatEntries,
    format,
    textColors,
    highlightColors,
    lastText,
    lastHighlight,
    color,
    alignEntries,
    align,
    undo: () => run(undoCommand),
    redo: () => run(redoCommand),
    clear: () => run(clearFormatting),
    linkEditing,
    linkDraft,
    currentLink,
    openLink,
    applyLink,
    cancelLink,
    unlink,
    followLink,
  }
}

export type NoteFormatting = ReturnType<typeof useNoteFormatting>
