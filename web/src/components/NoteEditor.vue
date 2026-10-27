<script setup lang="ts">
import { EditorContent } from '@tiptap/vue-3'
import { lift, wrapIn } from '@tiptap/pm/commands'
import type { Command } from '@tiptap/pm/state'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import NoteMenu, { type NoteMenuEntry } from '@/components/NoteMenu.vue'
import { redoCommand, undoCommand } from '@/notes/behaviour'
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
} from '@/notes/commands'
import { createNoteEditor, safeHref } from '@/notes/editor'
import { HIGHLIGHT_COLORS, TEXT_COLORS } from '@/notes/marks'
import '@/notes/editor.css'

/*
 * A note, open for reading and writing.
 *
 * The toolbar is the desktop's, in the desktop's words: Zotero's own note
 * editor has one fixed row of tools over the text, and so does this, because
 * it is the one way in that a finger, a keyboard and a screen reader all find
 * without being told. Markdown typed at the start of a line and the desktop's
 * keys work as well, as quicker ways to the same things. It is one tab stop,
 * moved through with the arrow keys; Alt+F10 reaches it from the text and
 * Escape goes back.
 *
 * The parent decides what to do with a change; this says only that one
 * happened, and never on opening a note.
 */

const { t } = useI18n()

const props = defineProps<{
  html: string
  editable: boolean
  /** Where an embedded image attachment's file is served. */
  imageUrl: (attachmentKey: string) => string
}>()

const emit = defineEmits<{ change: [html: string] }>()

const toolbar = ref<HTMLElement | null>(null)
const linkInput = ref<HTMLInputElement | null>(null)

/** Bumped on every transaction, so what the toolbar shows is read again. */
const tick = ref(0)
const linkEditing = ref(false)
const linkDraft = ref('')

const note = createNoteEditor({
  html: props.html,
  editable: props.editable,
  words: { and: t('and'), etAl: t('et al.') },
  imageUrl: props.imageUrl,
  placeholder: t('Write a note…'),
  label: t('Note'),
  onChange: html => emit('change', html),
  toggleLink: () => {
    openLink()
    return true
  },
  focusToolbar: () => {
    focusToolbar()
    return true
  },
})
const editor = shallowRef(note.editor)
editor.value.on('transaction', () => tick.value++)

const editable = computed(() => props.editable && !note.unsupportedSchema)

defineExpose({
  /** The note as it would be saved now. */
  html: note.html,
  focus: () => editor.value.commands.focus(),
})

onBeforeUnmount(() => editor.value.destroy())

/* ---- Running a command. ---- */

function run(command: Command): void {
  const { view } = editor.value
  command(view.state, view.dispatch, view)
  view.focus()
}

const schema = computed(() => editor.value.schema)

function markActive(name: string, attrs: Record<string, unknown> = {}): boolean {
  void tick.value
  return editor.value.isActive(name, attrs)
}

/* ---- What the toolbar shows. ---- */

type BlockId =
  | 'paragraph'
  | 'heading1'
  | 'heading2'
  | 'heading3'
  | 'codeBlock'
  | 'bulletList'
  | 'orderedList'
  | 'blockquote'

const formatEntries = computed<NoteMenuEntry[]>(() => {
  void tick.value
  const { state } = editor.value
  const nodes = schema.value.nodes
  const inList = listIsActive(state, nodes.bulletList!) || listIsActive(state, nodes.orderedList!)
  const inQuote = blockquoteIsActive(state)
  const blocks: [BlockId, string, boolean, string?][] = [
    ['paragraph', t('Paragraph'), blockIsActive(state, nodes.paragraph!) && !inList && !inQuote],
    ['heading1', t('Heading 1'), blockIsActive(state, nodes.heading!, { level: 1 }), 'h1'],
    ['heading2', t('Heading 2'), blockIsActive(state, nodes.heading!, { level: 2 }), 'h2'],
    ['heading3', t('Heading 3'), blockIsActive(state, nodes.heading!, { level: 3 }), 'h3'],
    ['codeBlock', t('Monospaced'), blockIsActive(state, nodes.codeBlock!), 'code'],
    ['bulletList', t('Bulleted List'), listIsActive(state, nodes.bulletList!)],
    ['orderedList', t('Numbered List'), listIsActive(state, nodes.orderedList!)],
    ['blockquote', t('Block Quote'), inQuote],
  ]
  const marks: [string, string, boolean, string?][] = [
    ['underline', t('Underline'), markActive('underline'), 'underline'],
    ['strike', t('Strikethrough'), markActive('strike'), 'strike'],
    ['sub', t('Subscript'), markActive('subsup', { type: 'sub' })],
    ['sup', t('Superscript'), markActive('subsup', { type: 'sup' })],
    ['code', t('Monospaced'), markActive('code'), 'code'],
  ]
  return [
    ...blocks.map(([id, label, checked, sample]) => ({ id, label, checked, sample, kind: 'radio' as const })),
    ...marks.map(([id, label, checked, sample], index) => ({
      id,
      label,
      checked,
      sample,
      kind: 'check' as const,
      separated: index === 0,
    })),
  ]
})

function format(id: string): void {
  const nodes = schema.value.nodes
  const marks: Record<string, [string, Record<string, unknown>?]> = {
    underline: ['underline'],
    strike: ['strike'],
    sub: ['subsup', { type: 'sub' }],
    sup: ['subsup', { type: 'sup' }],
    code: ['code'],
  }
  if (id in marks) {
    const [name, attrs] = marks[id]!
    editor.value.chain().focus().toggleMark(name, attrs).run()
    return
  }
  const blocks: Record<string, Command> = {
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
  run(blocks[id]!)
}

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

/** The address of the link the cursor is in, if any. */
const currentLink = computed<string | null>(() => {
  void tick.value
  return markActive('link') ? (editor.value.getAttributes('link').href ?? null) : null
})

async function openLink(): Promise<void> {
  if (!editable.value) return
  linkDraft.value = currentLink.value ?? ''
  linkEditing.value = true
  await nextTick()
  linkInput.value?.focus()
  linkInput.value?.select()
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

/* ---- The toolbar as one tab stop. ---- */

const current = ref(0)

function tools(): HTMLButtonElement[] {
  return Array.from(
    toolbar.value?.querySelectorAll<HTMLButtonElement>(':scope > button, :scope > .note-menu > button') ?? [],
  ).filter(button => !button.disabled)
}

function focusToolbar(): void {
  const all = tools()
  ;(all[current.value] ?? all[0])?.focus()
}

function toolbarKeydown(event: KeyboardEvent): void {
  const all = tools()
  const at = all.indexOf(document.activeElement as HTMLButtonElement)
  if (at < 0) return
  const to: Record<string, number> = {
    ArrowRight: (at + 1) % all.length,
    ArrowLeft: (at - 1 + all.length) % all.length,
    Home: 0,
    End: all.length - 1,
  }
  // Right moves on in reading order, which is leftwards in a language
  // written right to left.
  if (getComputedStyle(toolbar.value!).direction === 'rtl') {
    ;[to.ArrowRight, to.ArrowLeft] = [to.ArrowLeft!, to.ArrowRight!]
  }
  if (event.key in to) {
    event.preventDefault()
    current.value = to[event.key]!
    all[current.value]?.focus()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    editor.value.commands.focus()
  }
}

function toolbarFocusin(event: FocusEvent): void {
  const at = tools().indexOf(event.target as HTMLButtonElement)
  if (at >= 0) current.value = at
}

/** A press on a tool leaves the focus, and a phone's keyboard, in the text;
 *  a menu takes it when it opens, to be moved through. */
function keepTextFocused(event: MouseEvent): void {
  if ((event.target as Element).closest('button:not([aria-haspopup])')) event.preventDefault()
}

/** Escape in the text leaves it for the toolbar, the way out of a field where
 *  Tab indents. */
function editorKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && !event.defaultPrevented) {
    event.preventDefault()
    focusToolbar()
  }
}

/* ---- On a phone, the toolbar sits on the keyboard. ---- */

const keyboardInset = ref(0)

function measureKeyboard(): void {
  const viewport = window.visualViewport
  if (!viewport) return
  keyboardInset.value = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
}

onMounted(() => {
  window.visualViewport?.addEventListener('resize', measureKeyboard)
  window.visualViewport?.addEventListener('scroll', measureKeyboard)
})
onBeforeUnmount(() => {
  window.visualViewport?.removeEventListener('resize', measureKeyboard)
  window.visualViewport?.removeEventListener('scroll', measureKeyboard)
})
</script>

<template>
  <div class="note-editor" :style="{ '--note-keyboard-inset': `${keyboardInset}px` }">
    <p v-if="note.unsupportedSchema" class="card__inset note-editor__notice" role="status">
      {{ t('This note was written by a newer version of Zotero. It can be read here but not changed.') }}
    </p>

    <div v-if="editable" class="note-editor__bar">
      <div
        ref="toolbar"
        class="toolbar note-editor__toolbar"
        role="toolbar"
        :aria-label="t('Formatting')"
        aria-orientation="horizontal"
        @keydown="toolbarKeydown"
        @focusin="toolbarFocusin"
        @mousedown="keepTextFocused"
      >
        <button
          class="icon-button"
          type="button"
          :tabindex="current === 0 ? 0 : -1"
          :aria-label="t('Undo')"
          :title="t('Undo')"
          @click="run(undoCommand)"
        >
          <AppIcon name="undo" :size="22" />
        </button>
        <button
          class="icon-button"
          type="button"
          :tabindex="current === 1 ? 0 : -1"
          :aria-label="t('Redo')"
          :title="t('Redo')"
          @click="run(redoCommand)"
        >
          <AppIcon name="redo" :size="22" />
        </button>
        <span class="note-editor__divider" aria-hidden="true"></span>
        <NoteMenu
          :tabindex="current === 2 ? 0 : -1"
          :label="t('Format Text')"
          icon="format-text"
          :entries="formatEntries"
          @choose="format"
        />
        <button
          class="icon-button"
          :class="{ 'icon-button--on': markActive('strong') }"
          type="button"
          :tabindex="current === 3 ? 0 : -1"
          :aria-pressed="markActive('strong')"
          :aria-label="t('Bold')"
          :title="t('Bold')"
          @click="editor.chain().focus().toggleMark('strong').run()"
        >
          <AppIcon name="bold" :size="22" />
        </button>
        <button
          class="icon-button"
          :class="{ 'icon-button--on': markActive('em') }"
          type="button"
          :tabindex="current === 4 ? 0 : -1"
          :aria-pressed="markActive('em')"
          :aria-label="t('Italic')"
          :title="t('Italic')"
          @click="editor.chain().focus().toggleMark('em').run()"
        >
          <AppIcon name="italic" :size="22" />
        </button>
        <button
          class="icon-button"
          :class="{ 'icon-button--on': currentLink !== null || linkEditing }"
          type="button"
          :tabindex="current === 5 ? 0 : -1"
          :aria-pressed="currentLink !== null"
          :aria-label="t('Insert Link')"
          :title="t('Insert Link')"
          @click="openLink"
        >
          <AppIcon name="link" :size="22" />
        </button>
        <NoteMenu
          :tabindex="current === 6 ? 0 : -1"
          :label="t('Text Color')"
          icon="text-color"
          :bar="lastText"
          :entries="textColors"
          @choose="color('textColor', $event)"
        />
        <NoteMenu
          :tabindex="current === 7 ? 0 : -1"
          :label="t('Highlight Text')"
          icon="highlight"
          :bar="lastHighlight"
          :entries="highlightColors"
          @choose="color('backgroundColor', $event)"
        />
        <NoteMenu
          :tabindex="current === 8 ? 0 : -1"
          :label="t('Align')"
          icon="align"
          :entries="alignEntries"
          @choose="align"
        />
        <button
          class="icon-button"
          type="button"
          :tabindex="current === 9 ? 0 : -1"
          :aria-label="t('Clear Formatting')"
          :title="t('Clear Formatting')"
          @click="run(clearFormatting)"
        >
          <AppIcon name="clear-format" :size="22" />
        </button>
      </div>
      <slot name="status"></slot>
    </div>

    <!--
      Links get a bar of their own under the toolbar rather than a bubble over
      the text: it stays put in a narrow pane, under a finger and behind the
      keyboard, and it is in the reading order after the tools that opened it.
    -->
    <form v-if="editable && linkEditing" class="note-editor__link" @submit.prevent="applyLink">
      <label class="note-editor__link-label" for="note-link">{{ t('Enter Link') }}</label>
      <input
        id="note-link"
        ref="linkInput"
        v-model="linkDraft"
        class="note-editor__link-input"
        type="url"
        inputmode="url"
        autocomplete="url"
        spellcheck="false"
        @keydown.escape.prevent="cancelLink"
      />
      <button class="note-editor__link-button" type="submit">{{ t('Set') }}</button>
      <button class="note-editor__link-button" type="button" @click="cancelLink">{{ t('Cancel') }}</button>
    </form>
    <div v-else-if="currentLink !== null" class="note-editor__link">
      <span class="note-editor__link-address" dir="ltr">{{ currentLink }}</span>
      <button v-if="safeHref(currentLink)" class="note-editor__link-button" type="button" @click="followLink">
        {{ t('Open Link') }}
      </button>
      <template v-if="editable">
        <button class="note-editor__link-button" type="button" @click="openLink">{{ t('Edit') }}</button>
        <button class="note-editor__link-button" type="button" @click="unlink">{{ t('Unlink') }}</button>
      </template>
    </div>

    <EditorContent
      class="note-editor__text card__inset"
      :editor="editor"
      @keydown="editorKeydown"
    />
  </div>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.note-editor {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

/* The toolbar and, after it, whatever the parent says about saving. */
.note-editor__bar {
  position: sticky;
  z-index: 2;
  inset-block-start: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--md-spacing-1) var(--md-spacing-3);
}

/*
 * One row, whatever the width of the pane: a toolbar that wraps puts the same
 * tool in a different place every time the pane is resized. What does not fit
 * scrolls sideways, with the tools used most at its start. It stays at the top
 * of the pane while a long note scrolls under it.
 */
.note-editor__toolbar {
  overflow-x: auto;
  scrollbar-width: none;
  align-self: flex-start;
  max-width: 100%;
}

.note-editor__divider {
  flex: none;
  width: 1px;
  height: 1.5rem;
  margin-inline: 0.15rem;
  background: var(--md-sys-color-outline-variant);
}

.note-editor__notice {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.note-editor__link {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--md-spacing-2);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.note-editor__link-label {
  color: var(--md-sys-color-on-surface-variant);
}

.note-editor__link-input {
  flex: 1 1 12rem;
  min-width: 0;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

.note-editor__link-address {
  flex: 1 1 8rem;
  min-width: 0;
  overflow: hidden;
  color: var(--md-sys-color-on-surface-variant);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.note-editor__link-button {
  padding: 0.3rem 0.6rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.note-editor__text {
  cursor: text;
}

.note-editor__text:focus-within {
  outline: 2px solid var(--md-sys-color-primary);
  outline-offset: 1px;
}

/*
 * On a phone the toolbar rides on the on-screen keyboard while the note is
 * being typed in, where the thumb is; `--note-keyboard-inset` is how much of
 * the window the keyboard covers. Unverified on iOS: there was no device to
 * try it on.
 */
@media (pointer: coarse) and (max-width: 600px) {
  /* Room for the toolbar, which no longer takes any in the flow. */
  .note-editor:focus-within {
    padding-block-end: 4rem;
  }

  .note-editor:focus-within .note-editor__toolbar {
    position: fixed;
    z-index: 20;
    inset-inline: 0;
    inset-block: auto calc(var(--note-keyboard-inset, 0px));
    max-width: none;
    padding-block-end: calc(var(--md-spacing-1) + env(safe-area-inset-bottom, 0px));
    border-radius: 0;
    box-shadow: 0 -2px 8px rgb(0 0 0 / 12%);
  }
}
</style>
