<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useThemeStore, type ThemePreference } from '@/stores/theme'

const { t } = useI18n()

/**
 * The colour theme setting, as one icon that opens a menu.
 *
 * It used to be a segmented control with three labelled buttons, which made a
 * minor preference the loudest thing in the header. What it shows now is the
 * setting itself rather than the theme on screen: with "System" chosen, the
 * monitor glyph says the choice is being deferred, where a sun would claim a
 * decision nobody made.
 */
const theme = useThemeStore()

const OPTIONS: Array<{ value: ThemePreference; label: string; path: string }> = [
  {
    value: 'light',
    label: 'Light',
    path: 'M12 5.5v-2 M12 20.5v-2 M5.5 12h-2 M20.5 12h-2 M7.3 7.3L5.9 5.9 M18.1 18.1l-1.4-1.4 M7.3 16.7l-1.4 1.4 M18.1 5.9l-1.4 1.4 M15.5 12a3.5 3.5 0 11-7 0 3.5 3.5 0 017 0z',
  },
  { value: 'dark', label: 'Dark', path: 'M20 13.5A8.5 8.5 0 1110.5 4a6.8 6.8 0 009.5 9.5z' },
  { value: 'system', label: 'System', path: 'M3.75 5.75h16.5v10H3.75z M8.5 19.25h7 M12 15.75v3.5' },
]

const open = ref(false)
const root = useTemplateRef<HTMLElement>('root')
const trigger = useTemplateRef<HTMLButtonElement>('trigger')
const items = ref<HTMLButtonElement[]>([])

const current = computed(
  () => OPTIONS.find((option) => option.value === theme.preference) ?? OPTIONS[2],
)

function collect(element: unknown, index: number): void {
  if (element instanceof HTMLButtonElement) {
    items.value[index] = element
  }
}

async function toggle(): Promise<void> {
  open.value = !open.value
  if (!open.value) return

  // Opening moves focus into the menu, at whichever option is in force, so it
  // can be driven from the keyboard without tabbing through the list first.
  await nextTick()
  const index = OPTIONS.findIndex((option) => option.value === theme.preference)
  items.value[Math.max(index, 0)]?.focus()
}

function close({ refocus = true } = {}): void {
  if (!open.value) return
  open.value = false
  if (refocus) trigger.value?.focus()
}

function choose(value: ThemePreference): void {
  theme.setPreference(value)
  close()
}

/** Move between options with the arrow keys, wrapping at both ends. */
function step(from: number, by: number): void {
  const next = (from + by + OPTIONS.length) % OPTIONS.length
  items.value[next]?.focus()
}

function onKeydown(event: KeyboardEvent, index: number): void {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    step(index, 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    step(index, -1)
  } else if (event.key === 'Home') {
    event.preventDefault()
    items.value[0]?.focus()
  } else if (event.key === 'End') {
    event.preventDefault()
    items.value[OPTIONS.length - 1]?.focus()
  }
}

function onDocumentPointerDown(event: Event): void {
  // A click that lands anywhere else dismisses the menu, and does not steal
  // focus back to the trigger -- the pointer has already gone somewhere.
  if (!root.value?.contains(event.target as Node)) close({ refocus: false })
}

function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') close()
}

watch(open, (isOpen) => {
  // Listened for only while the menu is open: a handler per mounted menu,
  // running on every key of every keystroke, is a cost for nothing.
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointerDown)
    document.addEventListener('keydown', onDocumentKeydown)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
    document.removeEventListener('keydown', onDocumentKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<template>
  <div ref="root" class="theme-menu">
    <button
      ref="trigger"
      type="button"
      class="theme-menu__trigger"
      :aria-label="t('Colour theme: {name}', { name: t(current.label) })"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="toggle"
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path :d="current.path" />
      </svg>
    </button>

    <ul v-if="open" class="theme-menu__list" role="menu" :aria-label="t('Colour theme')">
      <li v-for="(option, index) in OPTIONS" :key="option.value" role="none">
        <button
          :ref="(element) => collect(element, index)"
          type="button"
          class="theme-menu__option"
          role="menuitemradio"
          :aria-checked="theme.preference === option.value"
          @click="choose(option.value)"
          @keydown="onKeydown($event, index)"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path :d="option.path" />
          </svg>
          <span class="theme-menu__label">{{ t(option.label) }}</span>
          <svg
            v-if="theme.preference === option.value"
            class="theme-menu__check"
            width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
          >
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.theme-menu {
  position: relative;
}

.theme-menu__trigger {
  display: grid;
  place-items: center;
  width: 2.25rem;
  height: 2.25rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-full);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.theme-menu__trigger:hover {
  background: var(--md-sys-color-surface-container-high);
}

.theme-menu__list {
  position: absolute;
  right: 0;
  z-index: 10;
  min-width: 10rem;
  margin: var(--md-spacing-2) 0 0;
  padding: var(--md-spacing-2);
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-high);
  box-shadow: 0 6px 16px rgb(0 0 0 / 18%);
  list-style: none;
}

.theme-menu__option {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-3);
  width: 100%;
  padding: 0.4rem 0.6rem;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  font-size: var(--md-sys-typescale-body-medium-size);
  text-align: left;
  cursor: pointer;
}

.theme-menu__option:hover {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

/* Split from the rule above rather than listed with it: `:focus-visible`
   arrived in Safari 15.4, and a browser that does not know a selector throws
   away the whole rule it appears in — hover included. */
.theme-menu__option:focus-visible {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.theme-menu__label {
  flex: 1;
}

.theme-menu__check {
  flex: none;
  color: var(--md-sys-color-primary);
}
</style>
