<script setup lang="ts">
import { onMounted, onUpdated, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import NoteMenu, { type NoteMenuEntry } from '@/components/NoteMenu.vue'
import type { NoteFormatting } from '@/notes/formatting'

/*
 * The note editor's tools, as one row.
 *
 * Two of them, from the same parts. `bubble` floats over selected text where
 * there is a mouse, as Linear's and Notion's do: the block the text is in,
 * then the character formats, link and colours, with alignment and the rarer
 * formats under More. `docked` sits on a phone's keyboard, where a selection
 * is made with handles the platform draws and a bar over them would cover
 * them: undo and redo first, which nothing else on a phone offers, then the
 * desktop's Format menu and the rest.
 *
 * Either way it is a toolbar in the WAI-ARIA sense: one tab stop, moved
 * through with the arrow keys, Home and End, and Escape back to the text.
 */

const { t } = useI18n()

const props = defineProps<{ f: NoteFormatting; variant: 'bubble' | 'docked' }>()

const emit = defineEmits<{ leave: [] }>()

const root = ref<HTMLElement | null>(null)
const current = ref(0)

function tools(): HTMLButtonElement[] {
  return Array.from(
    root.value?.querySelectorAll<HTMLButtonElement>(':scope > button, :scope > .note-menu > button') ?? [],
  ).filter(button => !button.disabled)
}

/** One tab stop: the tool last used takes it, the rest are reached by arrow. */
function syncTabindex(): void {
  const all = tools()
  if (current.value >= all.length) current.value = 0
  all.forEach((button, index) => button.setAttribute('tabindex', index === current.value ? '0' : '-1'))
}

onMounted(syncTabindex)
onUpdated(syncTabindex)

function keydown(event: KeyboardEvent): void {
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
  if (getComputedStyle(root.value!).direction === 'rtl') {
    ;[to.ArrowRight, to.ArrowLeft] = [to.ArrowLeft!, to.ArrowRight!]
  }
  if (event.key in to) {
    event.preventDefault()
    current.value = to[event.key]!
    syncTabindex()
    all[current.value]?.focus()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    emit('leave')
  }
}

function focusin(event: FocusEvent): void {
  const at = tools().indexOf(event.target as HTMLButtonElement)
  if (at >= 0) {
    current.value = at
    syncTabindex()
  }
}

/** A press on a tool leaves the focus, and a phone's keyboard, in the text;
 *  a menu takes it when it opens, to be moved through. */
function keepTextFocused(event: MouseEvent): void {
  if ((event.target as Element).closest('button:not([aria-haspopup])')) event.preventDefault()
}

/** The floating bar's More menu: alignment, indent, the rarer formats, and
 *  clearing them all. */
function moreEntries(): NoteMenuEntry[] {
  return [
    ...props.f.alignEntries.value,
    ...props.f.markEntries(['sub', 'sup'], true),
    { id: 'clear', label: t('Clear Formatting'), kind: 'action', separated: true },
  ]
}

function more(id: string): void {
  if (id === 'clear') props.f.clear()
  else if (id === 'sub' || id === 'sup') props.f.format(id)
  else props.f.align(id)
}

defineExpose({
  /** Moves the keyboard to the tool that holds the tab stop. */
  focus: () => {
    const all = tools()
    ;(all[current.value] ?? all[0])?.focus()
  },
})
</script>

<template>
  <div
    ref="root"
    class="toolbar note-toolbar"
    :class="`note-toolbar--${variant}`"
    role="toolbar"
    :aria-label="t('Formatting')"
    aria-orientation="horizontal"
    @keydown="keydown"
    @focusin="focusin"
    @mousedown="keepTextFocused"
  >
    <template v-if="variant === 'docked'">
      <button class="icon-button" type="button" :aria-label="t('Undo')" :title="t('Undo')" @click="f.undo()">
        <AppIcon name="undo" :size="22" />
      </button>
      <button class="icon-button" type="button" :aria-label="t('Redo')" :title="t('Redo')" @click="f.redo()">
        <AppIcon name="redo" :size="22" />
      </button>
      <span class="note-toolbar__divider" aria-hidden="true"></span>
      <NoteMenu :label="t('Format Text')" icon="format-text" :entries="f.formatEntries.value" @choose="f.format" />
    </template>
    <NoteMenu
      v-else
      :label="t('Format Text')"
      icon="format-text"
      :text="f.currentBlock.value"
      :entries="f.blockEntries.value"
      @choose="f.format"
    />

    <button
      v-for="id in variant === 'bubble' ? ['strong', 'em', 'underline', 'strike', 'code'] : ['strong', 'em']"
      :key="id"
      class="icon-button"
      :class="{ 'icon-button--on': f.markIsOn(id) }"
      type="button"
      :aria-pressed="f.markIsOn(id)"
      :aria-label="f.markLabels.value[id]"
      :title="f.markLabels.value[id]"
      @click="f.format(id)"
    >
      <AppIcon :name="{ strong: 'bold', em: 'italic', underline: 'underline', strike: 'strikethrough', code: 'code' }[id]!" :size="22" />
    </button>

    <button
      class="icon-button"
      :class="{ 'icon-button--on': f.currentLink.value !== null || f.linkEditing.value }"
      type="button"
      :aria-pressed="f.currentLink.value !== null"
      :aria-label="t('Insert Link')"
      :title="t('Insert Link')"
      @click="f.openLink()"
    >
      <AppIcon name="link" :size="22" />
    </button>
    <NoteMenu
      :label="t('Text Color')"
      icon="text-color"
      :bar="f.lastText.value"
      :entries="f.textColors.value"
      @choose="f.color('textColor', $event)"
    />
    <NoteMenu
      :label="t('Highlight Text')"
      icon="highlight"
      :bar="f.lastHighlight.value"
      :entries="f.highlightColors.value"
      @choose="f.color('backgroundColor', $event)"
    />

    <template v-if="variant === 'docked'">
      <NoteMenu :label="t('Align')" icon="align" :entries="f.alignEntries.value" @choose="f.align" />
      <button
        class="icon-button"
        type="button"
        :aria-label="t('Clear Formatting')"
        :title="t('Clear Formatting')"
        @click="f.clear()"
      >
        <AppIcon name="clear-format" :size="22" />
      </button>
    </template>
    <NoteMenu v-else :label="t('More')" icon="more" :entries="moreEntries()" @choose="more" />
  </div>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.note-toolbar {
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}

/* The corner of the item list's heading strip, not the pill other toolbars
   have: a row of many small tools over text reads as one strip. The buttons
   follow it a step smaller. */
/* Two classes, as this is a component's root: see NoteSlashMenu.vue. */
.toolbar.note-toolbar {
  border-radius: var(--md-sys-shape-corner-small);
}

.note-toolbar :deep(.icon-button),
.note-toolbar :deep(.note-menu__button) {
  border-radius: var(--md-sys-shape-corner-extra-small);
}

/* Raised over the text it floats above, by its shadow; the edge is the
   divider's, there only to keep it apart from text of the same shade. */
.toolbar.note-toolbar--bubble {
  border: 1px solid var(--md-sys-color-outline-variant);
  box-shadow: 0 6px 16px rgb(0 0 0 / 14%);
}

.note-toolbar--bubble .icon-button {
  width: 2rem;
  height: 2rem;
}

.note-toolbar__divider {
  flex: none;
  width: 1px;
  height: 1.5rem;
  margin-inline: 0.15rem;
  background: var(--md-sys-color-outline-variant);
}
</style>
