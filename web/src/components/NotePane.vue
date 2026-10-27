<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import ConflictNotice from '@/components/ConflictNotice.vue'
import NoteEditor from '@/components/NoteEditor.vue'
import { noteToTitle } from '@/items/titles'
import { EditConflict, type ItemEnvelope, type SaveItem } from '@/stores/library'

/*
 * A note in the item pane, saved as it is typed.
 *
 * The desktop saves a second after the last keystroke, and so does this; a
 * note left before then -- another item picked, the tab hidden or closed -- is
 * saved on the way out. Each save is the item's `note` and nothing else,
 * through the same write as every other field, so a change somebody made
 * meanwhile to anything but the note is carried over without asking. One made
 * to the note itself is a conflict, and both versions are offered by their
 * titles, in the desktop's words for its conflict window.
 *
 * Saving and saved are shown and not announced: a screen reader would
 * otherwise say one or the other every second while somebody types. A note
 * that could not be saved is announced.
 */

const { t } = useI18n()

const props = defineProps<{
  item: ItemEnvelope
  editable: boolean
  save?: SaveItem
  imageUrl: (attachmentKey: string) => string
  /** Put the cursor in the note once it is drawn, as for a note just made. */
  autofocus?: boolean
}>()

/** How long after the last change a note is saved: the desktop's debounce. */
const SAVE_DELAY = 1000

const editor = ref<InstanceType<typeof NoteEditor> | null>(null)
/** Bumped to draw the note again from the item, which discards the editor. */
const generation = ref(0)

type State = 'idle' | 'saving' | 'saved' | 'failed' | 'conflict'
const state = ref<State>('idle')
const failure = ref('')
const conflict = ref<{ mine: string; theirs: string } | null>(null)

/** The note as last typed and not yet sent. */
let pending: string | null = null
/** The note as last written, which the item will come back holding. */
let written = props.item.data.note ?? ''
let timer: ReturnType<typeof setTimeout> | undefined
let flight: Promise<void> | null = null

const editable = computed(() => props.editable && Boolean(props.save))

function change(html: string): void {
  pending = html
  if (state.value === 'saved') state.value = 'idle'
  clearTimeout(timer)
  timer = setTimeout(() => void flush(), SAVE_DELAY)
}

async function flush(): Promise<void> {
  clearTimeout(timer)
  if (flight) {
    await flight
  }
  if (pending === null || !props.save || state.value === 'conflict') return
  const html = pending
  pending = null
  state.value = 'saving'
  flight = (async () => {
    try {
      await props.save!({ note: html })
      written = html
      if (pending === null) state.value = 'saved'
    } catch (thrown) {
      if (pending === null) pending = html
      if (thrown instanceof EditConflict) {
        state.value = 'conflict'
        conflict.value = {
          mine: noteToTitle(pending),
          theirs: noteToTitle(thrown.fresh.data.note ?? ''),
        }
      } else {
        state.value = 'failed'
        failure.value = thrown instanceof Error ? thrown.message : String(thrown)
      }
    } finally {
      flight = null
    }
  })()
  await flight
  if (pending !== null && state.value === 'saving') await flush()
}

/** Writes the note as typed here over the other one. */
function keepMine(): void {
  conflict.value = null
  state.value = 'idle'
  void flush()
}

/** Takes the other one, which the item already holds, and drops what was typed. */
function keepTheirs(): void {
  conflict.value = null
  state.value = 'idle'
  pending = null
  written = props.item.data.note ?? ''
  generation.value++
}

function retry(): void {
  state.value = 'idle'
  void flush()
}

/*
 * The note changed elsewhere and came in by the live feed. Drawn again only
 * when nothing typed here is waiting, so it never takes text from under the
 * cursor; if something is, the save that follows finds the conflict.
 */
watch(
  () => props.item.data.note,
  (note) => {
    if ((note ?? '') === written) return
    if (pending !== null || flight || state.value === 'conflict') return
    written = note ?? ''
    generation.value++
  },
)

function hidden(): void {
  if (document.visibilityState === 'hidden') void flush()
}

onMounted(() => {
  if (props.autofocus) editor.value?.focus()
  document.addEventListener('visibilitychange', hidden)
  window.addEventListener('pagehide', flushNow)
})

function flushNow(): void {
  void flush()
}

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', hidden)
  window.removeEventListener('pagehide', flushNow)
  void flush()
})

/*
 * Full screen: the note alone in the window, for writing at length, as
 * Notion's full-page view and Linear's expanded editor give. It is a modal
 * dialog, so the page behind it cannot be reached by Tab or by a screen
 * reader, and Escape -- outside the text, where Escape moves to the tools --
 * brings the note back into the pane.
 */
const focused = ref(false)
const frame = ref<HTMLDialogElement | null>(null)
const toggle = ref<HTMLButtonElement | null>(null)
const frameId = `note-frame-${useId()}`
const title = computed(() => noteToTitle(props.item.data.note ?? '') || t('Note'))

async function enter(): Promise<void> {
  focused.value = true
  await nextTick()
  frame.value?.showModal()
  editor.value?.focus()
}

async function leave(): Promise<void> {
  if (!focused.value) return
  frame.value?.close()
  focused.value = false
  await nextTick()
  toggle.value?.focus()
}

onBeforeUnmount(() => frame.value?.close())

defineExpose({ focus: () => editor.value?.focus() })
</script>

<template>
  <section class="note-pane">
    <!--
      Moved into the dialog below while the note is written full-window, and
      back again after: the same editor, so nothing typed is lost on the way.
    -->
    <Teleport defer :to="`#${frameId}`" :disabled="!focused">
      <div class="note-pane__inner">
        <div class="note-pane__bar">
          <span v-if="state === 'saving'" class="note-pane__state">{{ t('Saving…') }}</span>
          <span v-else-if="state === 'saved'" class="note-pane__state">{{ t('Saved.') }}</span>
          <span v-else-if="state === 'failed'" class="note-pane__state note-pane__state--failed" role="alert">
            <span :title="failure">{{ t('Not saved.') }}</span>
            <button class="note-pane__retry" type="button" @click="retry">{{ t('Try Again') }}</button>
          </span>
          <button
            ref="toggle"
            class="icon-button note-pane__toggle"
            type="button"
            :aria-label="focused ? t('Exit Full Screen') : t('Enter Full Screen')"
            :title="focused ? t('Exit Full Screen') : t('Enter Full Screen')"
            @click="focused ? leave() : enter()"
          >
            <AppIcon :name="focused ? 'collapse' : 'expand'" :size="20" />
          </button>
        </div>
        <NoteEditor
          :key="generation"
          ref="editor"
          :html="item.data.note ?? ''"
          :editable="editable"
          :image-url="imageUrl"
          @change="change"
        />
        <ConflictNotice
          v-if="conflict"
          :id="`note-${item.key}-conflict`"
          :mine="conflict.mine"
          :theirs="conflict.theirs"
          @mine="keepMine"
          @theirs="keepTheirs"
        />
      </div>
    </Teleport>
    <dialog ref="frame" class="note-pane__dialog" :aria-label="title" @cancel.prevent="leave">
      <div :id="frameId" class="note-pane__column"></div>
    </dialog>
  </section>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.note-pane__inner {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

/* Quiet, as Google Docs' save state is: how the note stands, and the way into
   full screen, on one line over the text. */
.note-pane__bar {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  min-height: 2rem;
}

.note-pane__toggle {
  margin-inline-start: auto;
  border-radius: var(--md-sys-shape-corner-extra-small);
}

/* Not drawn until full screen opens it; then the whole window, the page's own
   colour, with the note in a column of a comfortable measure. */
.note-pane__dialog {
  width: 100vw;
  max-width: none;
  height: 100dvh;
  max-height: none;
  margin: 0;
  padding: var(--md-spacing-4) var(--md-spacing-4) var(--md-spacing-6);
  border: none;
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
}

.note-pane__dialog::backdrop {
  background: transparent;
}

.note-pane__column {
  max-width: 44rem;
  margin-inline: auto;
}

.note-pane__dialog :deep(.note-editor__text:focus-within) {
  outline: none;
}

.note-pane__dialog :deep(.ProseMirror) {
  min-height: calc(100dvh - 10rem);
  font-size: 1.0625rem;
}

.note-pane__state {
  display: inline-flex;
  align-items: center;
  gap: var(--md-spacing-2);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
  white-space: nowrap;
}

.note-pane__state--failed {
  color: var(--md-sys-color-error);
}

.note-pane__retry {
  padding: 0.2rem 0.5rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
  font: inherit;
  cursor: pointer;
}
</style>
