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
  /** Words on the button in place of the glyph, as the floating bar shows the
   *  block the cursor is in. The button's name then carries them too. */
  text?: string
  /** The glyph's size, where the button sits among smaller ones. */
  iconSize?: number
}>()

const emit = defineEmits<{ choose: [id: string]; closed: [] }>()

const open = ref(false)
/** Where the list is drawn, worked out from the button when it opens. */
const place = ref<Record<string, string>>({})
const root = ref<HTMLElement | null>(null)
const list = ref<HTMLElement | null>(null)
const button = ref<HTMLButtonElement | null>(null)
let anchor: DOMRect | null = null

function items(): HTMLButtonElement[] {
  return Array.from(list.value?.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]') ?? [])
}

/** Native focus can scroll an ancestor toolbar even though the menu is fixed.
 *  Keep the document still, and reveal the focused entry within the list only. */
function focusItem(item: HTMLButtonElement | undefined): void {
  const menu = list.value
  if (!item || !menu) return
  item.focus({ preventScroll: true })
  const bottom = item.offsetTop + item.offsetHeight
  if (item.offsetTop < menu.scrollTop) menu.scrollTop = item.offsetTop
  else if (bottom > menu.scrollTop + menu.clientHeight) menu.scrollTop = bottom - menu.clientHeight
}

async function toggle(): Promise<void> {
  if (open.value) {
    close()
    return
  }
  open.value = true
  await nextTick()
  position()
  // Apply the fixed coordinates before focus can scroll the unpositioned list
  // into view and dismiss it through the document's scroll handler.
  await nextTick()
  const all = items()
  focusItem(all.find(item => item.getAttribute('aria-checked') === 'true') ?? all[0])
}

/*
 * The list is fixed to the window rather than hung under the button, because
 * the toolbar scrolls sideways and so clips whatever hangs out of it. It
 * opens below the button where there is room and above it where there is not
 * -- on a phone the toolbar sits on the keyboard, at the bottom of the screen.
 */
function position(): void {
  const rect = button.value?.getBoundingClientRect()
  if (!rect) return
  anchor = rect
  const height = window.visualViewport?.height ?? window.innerHeight
  const below = height - rect.bottom
  const above = rect.top
  const style: Record<string, string> = {}
  if (below >= Math.min(320, above)) {
    style.top = `${rect.bottom + 4}px`
    style.maxHeight = `${Math.max(below - 12, 120)}px`
  } else {
    style.bottom = `${window.innerHeight - rect.top + 4}px`
    style.maxHeight = `${Math.max(above - 12, 120)}px`
  }
  const width = list.value?.offsetWidth ?? 0
  const rtl = getComputedStyle(button.value!).direction === 'rtl'
  // The page's width without its scrollbar, which a menu must not run under.
  const across = document.documentElement.clientWidth || window.innerWidth
  /* Hung from the button's far edge when it would not fit from the near one,
     as a menu at the end of a pane opens back towards the page. */
  const start = rtl || rect.left + width > across - 8 ? rect.right - width : rect.left
  style.left = `${Math.max(8, Math.min(start, across - width - 8))}px`
  place.value = style
}

/** A scroll that brought the trigger into view can arrive after the click.
 *  Dismiss only when the anchor moves, not on that queued notification. */
function scrolled(event: Event): void {
  if (!open.value || list.value?.contains(event.target as Node)) return
  const rect = button.value?.getBoundingClientRect()
  if (rect && anchor && rect.top === anchor.top && rect.left === anchor.left
      && rect.bottom === anchor.bottom && rect.right === anchor.right) return
  close()
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
    focusItem(all[to[event.key]!])
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

onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('scroll', scrolled, true)
  window.addEventListener('resize', close)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('scroll', scrolled, true)
  window.removeEventListener('resize', close)
})

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
      :aria-label="props.text ? `${props.label}: ${props.text}` : props.label"
      :title="props.label"
      :disabled="props.disabled"
      @click="toggle"
    >
      <span v-if="props.text" class="note-menu__text">{{ props.text }}</span>
      <span v-else class="note-menu__glyph">
        <AppIcon :name="props.icon" :size="props.iconSize ?? 22" />
        <span v-if="props.bar !== undefined" class="note-menu__bar" :style="{ background: props.bar ?? 'currentColor' }"></span>
      </span>
      <AppIcon name="chevron-down" :size="12" />
    </button>
    <ul v-if="open" ref="list" class="menu note-menu__list" :style="place" role="menu" :aria-label="props.label" @keydown="keydown">
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

.note-menu__text {
  max-width: 9rem;
  overflow: hidden;
  padding-inline-start: 0.25rem;
  font: inherit;
  font-size: var(--md-sys-typescale-body-medium-size);
  text-overflow: ellipsis;
  white-space: nowrap;
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

/* The edge, corner and shadow of the formatting bar these open from. */
.menu.note-menu__list {
  border-color: var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-small);
  box-shadow: 0 6px 16px rgb(0 0 0 / 14%);
}

.note-menu__list {
  position: fixed;
  z-index: 30;
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
