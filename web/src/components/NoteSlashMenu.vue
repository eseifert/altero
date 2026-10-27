<script setup lang="ts">
import { computed, ref, watch } from 'vue'

/*
 * The list "/" opens in a note: the block types whose names match what was
 * typed after the slash. The cursor stays in the text the whole time -- this
 * is a listbox the text field points into with `aria-activedescendant`, the
 * combobox pattern, so a screen reader hears the entry each arrow moves to
 * without the typing being interrupted.
 */

export interface SlashEntry {
  id: string
  label: string
  /** Other words it is found by: the English name, and Markdown's shorthand. */
  keywords: string[]
  /** What the entry draws as its sample. */
  sample?: string
}

const props = defineProps<{
  /** Where the slash is on screen; no list is drawn without it. */
  at: { left: number; top: number; bottom: number } | null
  query: string
  entries: SlashEntry[]
  /** The id each option's own id is made from, unique on the page. */
  idPrefix: string
}>()

const emit = defineEmits<{ choose: [id: string]; dismiss: [] }>()

function fold(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
}

const matches = computed(() => {
  const query = fold(props.query)
  if (!query) return props.entries
  const starts = (entry: SlashEntry) => [entry.label, ...entry.keywords].some(word => fold(word).startsWith(query))
  const contains = (entry: SlashEntry) => [entry.label, ...entry.keywords].some(word => fold(word).includes(query))
  return [...props.entries.filter(starts), ...props.entries.filter(e => !starts(e) && contains(e))]
})

const active = ref(0)
watch(matches, () => (active.value = 0))

/** The option the text field points at, for `aria-activedescendant`. */
const activeId = computed(() =>
  props.at && matches.value.length ? `${props.idPrefix}-${matches.value[active.value]!.id}` : null,
)

/** Below the slash where there is room, above it where there is not. */
const place = computed<Record<string, string>>(() => {
  if (!props.at) return {}
  const height = window.visualViewport?.height ?? window.innerHeight
  const below = height - props.at.bottom
  const style: Record<string, string> = { left: `${Math.max(8, Math.min(props.at.left, window.innerWidth - 248))}px` }
  if (below >= 240 || below >= props.at.top) {
    style.top = `${props.at.bottom + 4}px`
    style.maxHeight = `${Math.max(below - 12, 120)}px`
  } else {
    style.bottom = `${window.innerHeight - props.at.top + 4}px`
    style.maxHeight = `${Math.max(props.at.top - 12, 120)}px`
  }
  return style
})

/** A key pressed in the text while the list is open; true if it was ours. */
function onKey(event: KeyboardEvent): boolean {
  if (event.key === 'Escape') {
    emit('dismiss')
    return true
  }
  if (!matches.value.length) return false
  const count = matches.value.length
  if (event.key === 'ArrowDown') {
    active.value = (active.value + 1) % count
    return true
  }
  if (event.key === 'ArrowUp') {
    active.value = (active.value - 1 + count) % count
    return true
  }
  if (event.key === 'Enter' || event.key === 'Tab') {
    emit('choose', matches.value[active.value]!.id)
    return true
  }
  return false
}

defineExpose({ onKey, activeId, open: computed(() => Boolean(props.at && matches.value.length)) })
</script>

<template>
  <ul
    v-if="at && matches.length"
    :id="`${idPrefix}-list`"
    class="menu note-slash"
    :style="place"
    role="listbox"
  >
    <li
      v-for="(entry, index) in matches"
      :id="`${idPrefix}-${entry.id}`"
      :key="entry.id"
      class="menu__item note-slash__item"
      :class="{ 'note-slash__item--active': index === active }"
      role="option"
      :aria-selected="index === active"
      @mousedown.prevent="emit('choose', entry.id)"
      @mousemove="active = index"
    >
      <span :class="entry.sample ? `note-slash__sample note-slash__sample--${entry.sample}` : undefined">{{
        entry.label
      }}</span>
    </li>
  </ul>
</template>

<style scoped>
@import '@/styles/surfaces.css';

/* Two classes, because this list is a component's root, and a root also takes
   its parent's scoped styles: the parent's own `.menu` rule (absolute) would
   otherwise win or lose by the order the stylesheets happen to be bundled in. */
.menu.note-slash {
  position: fixed;
  border-color: var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-small);
  box-shadow: 0 6px 16px rgb(0 0 0 / 14%);
  z-index: 30;
  overflow-y: auto;
  width: 15rem;
}

.note-slash__item {
  cursor: pointer;
}

/* The entry Enter would choose, lit as a hovered entry is. */
.note-slash__item--active {
  background: var(--md-sys-state-hover-surface);
}

.note-slash__sample--h1 { font-size: 1.35em; font-weight: 600; }
.note-slash__sample--h2 { font-size: 1.2em; font-weight: 600; }
.note-slash__sample--h3 { font-size: 1.05em; font-weight: 600; }
.note-slash__sample--code { font-family: ui-monospace, monospace; }
</style>
