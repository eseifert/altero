<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import { itemTypeLabel, regularItemTypes } from '@/items/labels'
import { newItemMenu, recentTypes, rememberType } from '@/items/newitemtypes'
import { useLocaleStore } from '@/stores/locale'

/*
 * The item list's *New Item* button and the menu of types under it.
 *
 * The desktop's menu: the five types used last, then every type, each part in
 * alphabetical order of the names the schema gives them. Choosing one says
 * which type to make; the view makes it.
 */

const { t } = useI18n()
const locale = useLocaleStore()

const props = defineProps<{ disabled?: boolean }>()

const emit = defineEmits<{ create: [itemType: string] }>()

const open = ref(false)
const recent = ref<string[]>([])
const root = ref<HTMLElement | null>(null)
const list = ref<HTMLElement | null>(null)

const menu = computed(() =>
  newItemMenu(regularItemTypes(), recent.value, itemTypeLabel, locale.formatting),
)

function entries(): HTMLButtonElement[] {
  return Array.from(list.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
}

async function toggle(): Promise<void> {
  if (open.value) {
    open.value = false
    return
  }
  recent.value = recentTypes()
  open.value = true
  await nextTick()
  entries()[0]?.focus()
}

function close(): void {
  open.value = false
}

function choose(itemType: string): void {
  rememberType(itemType)
  open.value = false
  emit('create', itemType)
}

/** Up and down move through the menu, Home and End to its ends, as in any menu. */
function keydown(event: KeyboardEvent): void {
  const items = entries()
  const at = items.indexOf(document.activeElement as HTMLButtonElement)
  const to: Record<string, number> = {
    ArrowDown: (at + 1) % items.length,
    ArrowUp: (at - 1 + items.length) % items.length,
    Home: 0,
    End: items.length - 1,
  }
  if (event.key in to) {
    event.preventDefault()
    items[to[event.key]]?.focus()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    close()
    root.value?.querySelector<HTMLButtonElement>('[aria-haspopup]')?.focus()
  } else if (event.key === 'Tab') {
    close()
  }
}

function outside(event: PointerEvent): void {
  if (!root.value?.contains(event.target as Node)) close()
}

onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="root" class="new-item">
    <button
      class="icon-button"
      type="button"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="t('New Item')"
      :title="t('New Item')"
      :disabled="props.disabled"
      @click="toggle"
    >
      <AppIcon name="plus" :size="22" />
    </button>
    <ul v-if="open" ref="list" class="menu new-item__menu" role="menu" :aria-label="t('New Item')" @keydown="keydown">
      <li v-for="name in menu.primary" :key="`primary-${name}`" role="none">
        <button class="menu__item" role="menuitem" type="button" @click="choose(name)">
          {{ itemTypeLabel(name) }}
        </button>
      </li>
      <li role="separator" class="new-item__separator"></li>
      <li v-for="name in menu.all" :key="name" role="none">
        <button class="menu__item" role="menuitem" type="button" @click="choose(name)">
          {{ itemTypeLabel(name) }}
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.new-item {
  position: relative;
}

.new-item__menu {
  inset-block-start: calc(100% + 0.25rem);
  inset-inline-end: 0;
  max-height: min(28rem, 70vh);
  overflow-y: auto;
}

/* The size of the other tools over the list where a finger aims. */
@media (pointer: coarse) {
  .new-item > .icon-button {
    width: 2.5rem;
    height: 2.5rem;
  }
}

.new-item__separator {
  height: 1px;
  margin-block: 0.25rem;
  background: var(--md-sys-color-outline-variant);
}
</style>
