<script setup lang="ts">
import { PluginKey } from '@tiptap/pm/state'
import { EditorContent } from '@tiptap/vue-3'
import { BubbleMenu } from '@tiptap/vue-3/menus'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import NoteSlashMenu, { type SlashEntry } from '@/components/NoteSlashMenu.vue'
import NoteToolbar from '@/components/NoteToolbar.vue'
import { createNoteEditor, safeHref } from '@/notes/editor'
import { type BlockId, useNoteFormatting } from '@/notes/formatting'
import { dismissSlash, SlashCommands, type SlashQuery } from '@/notes/slash'
import '@/notes/editor.css'

/*
 * A note, open for reading and writing, drawn as part of the page rather than
 * as a field on it -- the way Linear and Notion draw a document.
 *
 * Nothing stands over the text until it is wanted. Where there is a mouse,
 * selecting text raises a bar of formats over it, and "/" opens a list of
 * block types; Markdown typed at the start of a line and the desktop's keys
 * work as well. Where there is a finger, the tools sit on the keyboard while
 * the note is being written: a bar over a selection would cover the handles
 * the phone draws to change it.
 *
 * The keyboard reaches the tools from anywhere in the text with Alt+F10, as in
 * Zotero's own editor, or Escape, which is also the way out of a field in
 * which Tab indents; Escape in the tools comes back.
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

/** A finger rather than a mouse: the tools go on the keyboard. */
const coarse = ref(window.matchMedia?.('(pointer: coarse)').matches ?? false)

const slash = ref<{ query: SlashQuery; at: { left: number; top: number; bottom: number } } | null>(null)
const slashMenu = ref<InstanceType<typeof NoteSlashMenu> | null>(null)

const note = createNoteEditor({
  html: props.html,
  editable: props.editable,
  words: { and: t('and'), etAl: t('et al.') },
  imageUrl: props.imageUrl,
  placeholder: t('Write, or type / for headings, lists and more…'),
  label: t('Note'),
  onChange: html => emit('change', html),
  toggleLink: () => {
    void openLink()
    return true
  },
  focusToolbar: () => {
    void focusTools()
    return true
  },
  extensions: [
    SlashCommands.configure({
      onChange: (query, view) => {
        if (!query) {
          slash.value = null
          return
        }
        const { left, top, bottom } = view.coordsAtPos(query.from)
        slash.value = { query, at: { left, top, bottom } }
      },
      onKeyDown: event => slashMenu.value?.onKey(event) ?? false,
    }),
  ],
})
const editor = shallowRef(note.editor)
const f = useNoteFormatting(editor)

const editable = computed(() => props.editable && !note.unsupportedSchema)

/** Whether the reader has put the cursor anywhere yet. */
let placed = false
note.editor.on('focus', () => (placed = true))

defineExpose({
  /** The note as it would be saved now. */
  html: note.html,
  /** Back where the cursor was, or after the last word if it never was. */
  focus: () => editor.value.commands.focus(placed ? null : 'end'),
})

onBeforeUnmount(() => editor.value.destroy())

/* ---- The bar over a selection. ---- */

const bubbleKey = new PluginKey('noteBubble')
const bubbleToolbar = ref<InstanceType<typeof NoteToolbar> | null>(null)
const dockedToolbar = ref<InstanceType<typeof NoteToolbar> | null>(null)
const linkInput = ref<HTMLInputElement | null>(null)
/** Raised from the keyboard over no selection, until Escape lowers it. */
const raised = ref(false)

const bubbleOptions = { strategy: 'fixed' as const, placement: 'top' as const, offset: 8 }

function shouldShowBubble({
  view,
  state,
  element,
}: {
  view: { hasFocus: () => boolean }
  state: typeof editor.value.state
  element: HTMLElement
}): boolean {
  if (!editable.value || coarse.value) return false
  if (!view.hasFocus() && !element.contains(document.activeElement)) return false
  if (raised.value || f.linkEditing.value) return true
  const { empty, from, to } = state.selection
  if (!empty) return state.doc.textBetween(from, to).length > 0
  return editor.value.isActive('link')
}

function showBubble(): void {
  editor.value.view.dispatch(editor.value.state.tr.setMeta(bubbleKey, 'show'))
}

async function focusTools(): Promise<void> {
  if (!editable.value) return
  if (coarse.value) {
    dockedToolbar.value?.focus()
    return
  }
  raised.value = true
  showBubble()
  await nextTick()
  bubbleToolbar.value?.focus()
}

function leaveTools(): void {
  raised.value = false
  editor.value.commands.focus()
}

/* ---- Links, edited in the bar over them. ---- */

async function openLink(): Promise<void> {
  await f.openLink()
  if (!coarse.value) showBubble()
  await nextTick()
  linkInput.value?.focus()
  linkInput.value?.select()
}

/** Escape in the text leaves it for the tools: the way out of a field where
 *  Tab indents. */
function editorKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && !event.defaultPrevented && !slash.value) {
    event.preventDefault()
    void focusTools()
  }
}

/* ---- "/" ---- */

const slashEntries = computed<SlashEntry[]>(() => {
  const labels = f.blockLabels.value
  const words: Record<BlockId, string[]> = {
    paragraph: ['Paragraph', 'text', 'p'],
    heading1: ['Heading 1', 'h1', '#'],
    heading2: ['Heading 2', 'h2', '##'],
    heading3: ['Heading 3', 'h3', '###'],
    codeBlock: ['Monospaced', 'code', '```'],
    bulletList: ['Bulleted List', 'bullet', 'ul', '-'],
    orderedList: ['Numbered List', 'numbered', 'ol', '1.'],
    blockquote: ['Block Quote', 'quote', '>'],
  }
  const samples: Partial<Record<BlockId, string>> = { heading1: 'h1', heading2: 'h2', heading3: 'h3', codeBlock: 'code' }
  return [
    ...(Object.keys(words) as BlockId[]).map(id => ({ id, label: labels[id], keywords: words[id], sample: samples[id] })),
    { id: 'divider', label: t('Divider'), keywords: ['Divider', 'hr', 'rule', '---'] },
  ]
})

function chooseSlash(id: string): void {
  const query = slash.value?.query
  if (!query) return
  editor.value.chain().focus().deleteRange({ from: query.from, to: query.to }).run()
  if (id === 'divider') {
    editor.value.chain().focus().insertContent({ type: 'horizontalRule' }).run()
  } else if (!f.blockEntries.value.find(entry => entry.id === id)?.checked) {
    f.run(f.blockCommand(id as BlockId))
  }
}

const slashId = `note-slash-${useId()}`

// The text field points into the list while it is open: the combobox
// pattern, which lets a screen reader follow the arrows without the cursor
// leaving the text.
watch(
  () => slashMenu.value?.activeId ?? null,
  activeId => {
    const dom = editor.value.view.dom
    if (activeId) {
      dom.setAttribute('aria-controls', `${slashId}-list`)
      dom.setAttribute('aria-activedescendant', activeId)
    } else {
      dom.removeAttribute('aria-controls')
      dom.removeAttribute('aria-activedescendant')
    }
  },
)

/* ---- On a phone, the toolbar sits on the keyboard. ---- */

const keyboardInset = ref(0)

function measureKeyboard(): void {
  const viewport = window.visualViewport
  if (!viewport) return
  keyboardInset.value = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
}

const pointerQuery = window.matchMedia?.('(pointer: coarse)')
function pointerChanged(event: MediaQueryListEvent): void {
  coarse.value = event.matches
}

onMounted(() => {
  window.visualViewport?.addEventListener('resize', measureKeyboard)
  window.visualViewport?.addEventListener('scroll', measureKeyboard)
  pointerQuery?.addEventListener?.('change', pointerChanged)
})
onBeforeUnmount(() => {
  window.visualViewport?.removeEventListener('resize', measureKeyboard)
  window.visualViewport?.removeEventListener('scroll', measureKeyboard)
  pointerQuery?.removeEventListener?.('change', pointerChanged)
})
</script>

<template>
  <div
    class="note-editor"
    :class="{ 'note-editor--docked': coarse }"
    :style="{ '--note-keyboard-inset': `${keyboardInset}px` }"
  >
    <p v-if="note.unsupportedSchema" class="card__inset note-editor__notice" role="status">
      {{ t('This note was written by a newer version of Zotero. It can be read here but not changed.') }}
    </p>

    <NoteToolbar
      v-if="editable && coarse"
      ref="dockedToolbar"
      class="note-editor__docked"
      :f="f"
      variant="docked"
      @leave="leaveTools"
    />

    <!--
      Links get a bar of their own on a phone, under the tools, where it stays
      put behind the keyboard; with a mouse the same controls are in the bar
      over the link.
    -->
    <template v-if="editable && coarse">
      <form v-if="f.linkEditing.value" class="note-editor__link" @submit.prevent="f.applyLink()">
        <label class="note-editor__link-label" :for="`${slashId}-link`">{{ t('Enter Link') }}</label>
        <input
          :id="`${slashId}-link`"
          ref="linkInput"
          v-model="f.linkDraft.value"
          class="note-editor__link-input"
          type="url"
          dir="ltr"
          inputmode="url"
          autocomplete="url"
          spellcheck="false"
          @keydown.escape.prevent="f.cancelLink()"
        />
        <button class="note-editor__link-button" type="submit">{{ t('Set') }}</button>
        <button class="note-editor__link-button" type="button" @click="f.cancelLink()">{{ t('Cancel') }}</button>
      </form>
      <div v-else-if="f.currentLink.value !== null" class="note-editor__link">
        <span class="note-editor__link-address" dir="ltr">{{ f.currentLink.value }}</span>
        <button v-if="safeHref(f.currentLink.value)" class="note-editor__link-button" type="button" @click="f.followLink()">
          {{ t('Open Link') }}
        </button>
        <button class="note-editor__link-button" type="button" @click="openLink">{{ t('Edit') }}</button>
        <button class="note-editor__link-button" type="button" @click="f.unlink()">{{ t('Unlink') }}</button>
      </div>
    </template>

    <EditorContent class="note-editor__text" :editor="editor" @keydown="editorKeydown">
    </EditorContent>

    <BubbleMenu
      v-if="editable && !coarse"
      :editor="editor"
      :plugin-key="bubbleKey"
      :should-show="shouldShowBubble"
      :options="bubbleOptions"
      :update-delay="0"
      class="note-editor__bubble"
      @keydown.escape="raised = false"
    >
      <form v-if="f.linkEditing.value" class="toolbar note-editor__link note-editor__link--floating" @submit.prevent="f.applyLink()">
        <label class="visually-hidden" :for="`${slashId}-link`">{{ t('Enter Link') }}</label>
        <input
          :id="`${slashId}-link`"
          ref="linkInput"
          v-model="f.linkDraft.value"
          class="note-editor__link-input"
          type="url"
          inputmode="url"
          autocomplete="url"
          spellcheck="false"
          :placeholder="t('Enter Link')"
          dir="ltr"
          @keydown.escape.prevent.stop="f.cancelLink()"
        />
        <button class="note-editor__link-button" type="submit">{{ t('Set') }}</button>
      </form>
      <div
        v-else-if="!raised && editor.state.selection.empty && f.currentLink.value !== null"
        class="toolbar note-editor__link note-editor__link--floating"
      >
        <span class="note-editor__link-address" dir="ltr">{{ f.currentLink.value }}</span>
        <button v-if="safeHref(f.currentLink.value)" class="note-editor__link-button" type="button" @click="f.followLink()">
          {{ t('Open Link') }}
        </button>
        <button class="note-editor__link-button" type="button" @click="openLink">{{ t('Edit') }}</button>
        <button class="note-editor__link-button" type="button" @click="f.unlink()">{{ t('Unlink') }}</button>
      </div>
      <NoteToolbar v-else ref="bubbleToolbar" :f="f" variant="bubble" @leave="leaveTools" />
    </BubbleMenu>

    <NoteSlashMenu
      ref="slashMenu"
      :at="slash?.at ?? null"
      :query="slash?.query.query ?? ''"
      :entries="slashEntries"
      :id-prefix="slashId"
      @choose="chooseSlash"
      @dismiss="dismissSlash(editor.view)"
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

/*
 * The text is the page: no box, no fill, only a hairline frame while it has
 * the keyboard, so there is still something to say where typing goes.
 */
.note-editor__text {
  border-radius: var(--md-sys-shape-corner-small);
  cursor: text;
}

.note-editor__text:focus-within {
  outline: 1px solid var(--md-sys-color-outline-variant);
  outline-offset: 0.4rem;
}

.note-editor__notice {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
}

.note-editor__link {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--md-spacing-2);
  font-size: var(--md-sys-typescale-body-medium-size);
}

/* With a mouse the link's controls float over it, drawn as the formats are. */
.toolbar.note-editor__link--floating {
  flex-wrap: nowrap;
  max-width: min(28rem, 90vw);
  padding: var(--md-spacing-1) var(--md-spacing-2);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-small);
  box-shadow: 0 6px 16px rgb(0 0 0 / 14%);
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
  flex: none;
  padding: 0.3rem 0.6rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.note-editor__bubble {
  z-index: 25;
}

/* Over the text the link's errands are words, not boxes, as the formats
   beside them are glyphs: the bar is the container. */
.note-editor__link--floating .note-editor__link-button {
  border: none;
  border-radius: var(--md-sys-shape-corner-extra-small);
  background: none;
  color: var(--md-sys-color-primary);
}

.note-editor__link--floating .note-editor__link-button:hover {
  background: var(--md-sys-state-hover-surface);
}

/*
 * The tools on a finger's device: shown only while the note is being written,
 * at the top of the pane where the screen is wide, and on the keyboard where
 * it is narrow -- where the thumb is. `--note-keyboard-inset` is how much of
 * the window the keyboard covers. Unverified on iOS: there was no device.
 */
.note-editor__docked {
  position: sticky;
  z-index: 2;
  inset-block-start: 0;
  align-self: flex-start;
}

.note-editor--docked:not(:focus-within) .note-editor__docked {
  display: none;
}

@media (max-width: 600px) {
  /* Room for the toolbar, which no longer takes any in the flow. */
  .note-editor--docked:focus-within {
    padding-block-end: 4rem;
  }

  .note-editor--docked:focus-within .note-editor__docked {
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
