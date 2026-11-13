<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
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

const OPTIONS: Array<{ value: ThemePreference; label: () => string }> = [
  { value: 'light', label: () => t('Light') },
  { value: 'dark', label: () => t('Dark') },
  { value: 'system', label: () => t('System') },
]

const open = ref(false)
const root = useTemplateRef<HTMLElement>('root')
const trigger = useTemplateRef<HTMLButtonElement>('trigger')
const list = useTemplateRef<HTMLElement>('list')
const items = ref<HTMLButtonElement[]>([])

// Use the top layer only when the menu can also stay attached to its trigger.
// The ordinary positioned menu remains the fallback; no polyfill is needed.
const nativeMenu = typeof HTMLElement !== 'undefined'
  && 'popover' in HTMLElement.prototype
  && typeof HTMLElement.prototype.showPopover === 'function'
  && typeof ToggleEvent !== 'undefined' && 'source' in ToggleEvent.prototype
  && globalThis.CSS?.supports?.('anchor-name', '--theme-menu') === true
  && CSS.supports('position-anchor', '--theme-menu')
  && CSS.supports('position-area', 'block-end span-inline-start')
  && CSS.supports('position-try-fallbacks', 'flip-block, flip-inline, flip-block flip-inline')
let openingIndex: number | null = null

const current = computed(
  () => OPTIONS.find((option) => option.value === theme.preference) ?? OPTIONS[2],
)

function collect(element: unknown, index: number): void {
  if (element instanceof HTMLButtonElement) {
    items.value[index] = element
  }
}

async function toggle(event: MouseEvent): Promise<void> {
  if (open.value) close()
  else await show(undefined, event.detail === 0)
}

async function show(index = OPTIONS.findIndex(option => option.value === theme.preference), enter = true): Promise<void> {
  open.value = true
  openingIndex = enter ? Math.max(index, 0) : null

  await nextTick()
  if (!open.value) return
  if (nativeMenu && list.value && trigger.value) {
    if (!list.value.matches(':popover-open')) {
      // The source both anchors the menu and keeps its trigger in the native
      // light-dismiss group. TypeScript's DOM declarations predate this option.
      const menu = list.value as HTMLElement & { showPopover(options: { source: HTMLElement }): void }
      menu.showPopover({ source: trigger.value })
      // Native opening focuses from the toggle event, after promotion.
      return
    }
  }
  focusOnOpen()
}

function focusOnOpen(): void {
  if (openingIndex === null) trigger.value?.focus()
  else items.value[openingIndex]?.focus()
}

function onToggle(event: Event): void {
  // A queued event for a replaced menu must not close its successor.
  if (event.currentTarget !== list.value) return
  if ((event as ToggleEvent).newState === 'closed') open.value = false
  else if (open.value) focusOnOpen()
}

function close({ refocus = true } = {}): void {
  if (!open.value) return
  if (refocus) trigger.value?.focus()
  if (nativeMenu && list.value?.matches(':popover-open')) list.value.hidePopover()
  open.value = false
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
  } else if (event.key === 'Tab') {
    // Let native Tab navigation continue from the trigger, in either direction.
    close()
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

function onDocumentFocusIn(event: FocusEvent): void {
  if (!root.value?.contains(event.target as Node)) close({ refocus: false })
}

watch(open, (isOpen) => {
  // Listened for only while the menu is open: a handler per mounted menu,
  // running on every key of every keystroke, is a cost for nothing.
  if (isOpen) {
    if (!nativeMenu) document.addEventListener('pointerdown', onDocumentPointerDown)
    document.addEventListener('keydown', onDocumentKeydown)
    document.addEventListener('focusin', onDocumentFocusIn)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
    document.removeEventListener('keydown', onDocumentKeydown)
    document.removeEventListener('focusin', onDocumentFocusIn)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('focusin', onDocumentFocusIn)
})
</script>

<template>
  <div ref="root" class="theme-menu">
    <button
      ref="trigger"
      type="button"
      class="theme-menu__trigger"
      :aria-label="t('Color theme: {name}', { name: current.label() })"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="toggle"
      @keydown.down.prevent="show(0)"
      @keydown.up.prevent="show(OPTIONS.length - 1)"
    >
      <AppIcon :name="`theme-${current.value}`" :size="24" />
    </button>

    <ul
      v-if="open"
      ref="list"
      class="theme-menu__list"
      role="menu"
      :popover="nativeMenu ? 'auto' : undefined"
      :aria-label="t('Color theme')"
      @toggle="onToggle"
    >
      <li v-for="(option, index) in OPTIONS" :key="option.value" role="none">
        <button
          :ref="(element) => collect(element, index)"
          type="button"
          class="theme-menu__option"
          role="menuitemradio"
          tabindex="-1"
          :aria-checked="theme.preference === option.value"
          @click="choose(option.value)"
          @keydown="onKeydown($event, index)"
        >
          <AppIcon :name="`theme-${option.value}`" :size="22" />
          <span class="theme-menu__label">{{ option.label() }}</span>
          <AppIcon
            v-if="theme.preference === option.value"
            name="check"
            class="theme-menu__check"
            :size="20"
          />
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
  background: var(--md-sys-state-hover-surface);
}

.theme-menu__trigger[aria-expanded='true'] {
  background: var(--md-sys-color-secondary-container);
}

.theme-menu__list {
  position: absolute;
  inset-inline-end: 0;
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

/* Never reset popover centering without the positioning features we use. */
@supports (position-area: block-end span-inline-start) and (position-try-fallbacks: flip-block) {
  .theme-menu__list[popover] {
    position: fixed;
    inset: auto;
    position-area: block-end span-inline-start;
    position-try-fallbacks: flip-block, flip-inline, flip-block flip-inline;
    justify-self: end;
    inline-size: max-content;
    min-inline-size: 0;
    max-inline-size: calc(100vw - 1rem);
    max-block-size: calc(100vh - 1rem);
    overflow: auto;
    margin: var(--md-spacing-2) 0;
    color: var(--md-sys-color-on-surface);
  }
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
  text-align: start;
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
