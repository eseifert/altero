<script setup lang="ts">
import { computed } from 'vue'

import { sidebarIcon } from '@/items/sidebaricons'

/**
 * One sidebar glyph.
 *
 * Decorative by default: the row it sits in already carries the name as text,
 * so repeating it to a screen reader would only be noise. `labelled` turns the
 * title back on for a row that has no visible text of its own.
 */
const props = withDefaults(defineProps<{ name: string; size?: number; labelled?: boolean }>(), {
  size: 16,
  labelled: false,
})

const icon = computed(() => sidebarIcon(props.name))
</script>

<template>
  <svg
    class="sidebar-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    :role="labelled ? 'img' : 'presentation'"
    :aria-hidden="labelled ? undefined : 'true'"
    :aria-label="labelled ? icon.label : undefined"
  >
    <title v-if="labelled">{{ icon.label }}</title>
    <path v-for="(d, index) in icon.paths" :key="index" :d="d" />
  </svg>
</template>

<style scoped>
.sidebar-icon {
  flex: none;
  color: var(--md-sys-color-on-surface-variant);
}
</style>
