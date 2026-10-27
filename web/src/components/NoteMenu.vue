<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'

/*
 * One of the note toolbar's menus: a button in the toolbar and the list that
 * opens under it.
 *
 * Each entry says whether it is what the text already is, as a radio (one
 * block type, one colour) or a checkbox (a character format, which combine),
 * so a screen reader announces the state the toolbar's lit buttons show. The
 * keys are a menu's: up and down, Home and End, Escape back to the button.
 * Left and right are kept from the toolbar, which would otherwise move on to
 * the next button with the menu still open.
 */

export interface NoteMenuEntry {
  id: string
  label: string
  /** `radio` for one of a set, `check` for one that combines. */
  kind: 'radio' | 'check' | 'action'
  checked?: boolean
  /** A colour swatch drawn before the label. */
  swatch?: string
  /** Starts a new group, with a rule above it. */
  separated?: boolean
  /** Drawn in the style it applies, as the desktop's Format menu draws it. */
  sample?: string
}

const props = defineProps<{
  label: string
  icon: string
  entries: NoteMenuEntry[]
  disabled?: boolean
  /** The colour bar under a colour button's glyph. */
  bar?: string | null
  /** The button's place in its toolbar's single tab stop. */
  tabindex?: number
}>()

const emit = defineEmits<{ choose: [id: string]; closed: [] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const list = ref<HTMLElement | null>(null)
const button = ref<HTMLButtonElement | null>(null)

function items(): HTMLButtonElement[] {
  return Array.from(list.value?.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]') ?? [])
}

async function toggle(): Promise<void> {
  if (open.value) {
    close()
    return
  }
  open.value = true
  await nextTick()
  const all = items()
  ;(all.find(item => item.getAttribute('aria-checked') === 'true') ?? all[0])?.focus()
}

function close(): void {
  if (!open.value) return
  open.value = false
  emit('closed')
}

function choose(id: string): void {
  open.value = false
  emit('choose', id)
}

function keydown(event: KeyboardEvent): void {
  const all = items()
  const at = all.indexOf(document.activeElement as HTMLButtonElement)
  const to: Record<string, number> = {
    ArrowDown: (at + 1) % all.length,
    ArrowUp: (at - 1 + all.length) % all.length,
    Home: 0,
    End: all.length - 1,
  }
  if (event.key in to) {
    event.preventDefault()
    all[to[event.key]!]?.focus()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    open.value = false
    button.value?.focus()
  } else if (event.key === 'Tab') {
    close()
  }
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') event.stopPropagation()
}

function outside(event: PointerEvent): void {
  if (open.value && !root.value?.contains(event.target as Node)) close()
}

onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))

defineExpose({ button })
</script>

<template>
  <div ref="root" class="note-menu">
    <button
      ref="button"
      class="icon-button note-menu__button"
      type="button"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="props.label"
      :title="props.label"
      :disabled="props.disabled"
      :tabindex="props.tabindex"
      @click="toggle"
    >
      <span class="note-menu__glyph">
        <AppIcon :name="props.icon" :size="22" />
        <span v-if="props.bar !== undefined" class="note-menu__bar" :style="{ background: props.bar ?? 'currentColor' }"></span>
      </span>
      <AppIcon name="chevron-down" :size="12" />
    </button>
    <ul v-if="open" ref="list" class="menu note-menu__list" role="menu" :aria-label="props.label" @keydown="keydown">
      <template v-for="entry in props.entries" :key="entry.id">
        <li v-if="entry.separated" role="separator" class="note-menu__separator"></li>
        <li role="none">
          <button
            class="menu__item note-menu__item"
            :role="entry.kind === 'radio' ? 'menuitemradio' : entry.kind === 'check' ? 'menuitemcheckbox' : 'menuitem'"
            :aria-checked="entry.kind === 'action' ? undefined : Boolean(entry.checked)"
            type="button"
            @click="choose(entry.id)"
          >
            <span class="note-menu__mark" aria-hidden="true">
              <AppIcon v-if="entry.checked" name="check" :size="16" />
            </span>
            <span v-if="entry.swatch" class="note-menu__swatch" :style="{ background: entry.swatch }" aria-hidden="true"></span>
            <span :class="entry.sample ? `note-menu__sample note-menu__sample--${entry.sample}` : undefined">{{ entry.label }}</span>
          </button>
        </li>
      </template>
    </ul>
  </div>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.note-menu {
  position: relative;
  flex: none;
}

/* Wider than a plain icon button by its chevron, which is what says a menu
   opens rather than a format being applied. */
.note-menu__button {
  display: flex;
  gap: 0.05rem;
  width: auto;
  padding-inline: 0.35rem 0.25rem;
  border-radius: var(--md-sys-shape-corner-full);
}

.note-menu__glyph {
  display: grid;
  place-items: center;
}

/* The colour last chosen, under the glyph, as every editor draws its colour
   buttons; `currentColor` when none has been. */
.note-menu__bar {
  width: 1rem;
  height: 0.2rem;
  margin-block-start: -0.2rem;
  border-radius: 0.1rem;
}

.note-menu__list {
  inset-block-start: calc(100% + 0.25rem);
  inset-inline-start: 0;
  max-height: min(24rem, 60vh);
  overflow-y: auto;
}

.note-menu__item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  white-space: nowrap;
}

.note-menu__mark {
  display: grid;
  flex: none;
  place-items: center;
  width: 1rem;
}

.note-menu__swatch {
  flex: none;
  width: 0.9rem;
  height: 0.9rem;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: 50%;
}

.note-menu__separator {
  height: 1px;
  margin-block: 0.25rem;
  background: var(--md-sys-color-outline-variant);
}

.note-menu__sample--h1 { font-size: 1.35em; font-weight: 600; }
.note-menu__sample--h2 { font-size: 1.2em; font-weight: 600; }
.note-menu__sample--h3 { font-size: 1.05em; font-weight: 600; }
.note-menu__sample--code { font-family: ui-monospace, monospace; }
.note-menu__sample--strong { font-weight: 700; }
.note-menu__sample--em { font-style: italic; }
.note-menu__sample--underline { text-decoration: underline; }
.note-menu__sample--strike { text-decoration: line-through; }

@media (pointer: coarse) {
  .note-menu__button {
    height: 2.5rem;
  }
}
</style>
