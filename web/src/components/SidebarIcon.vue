<script setup lang="ts">
import { computed } from 'vue'

import SvgIcon from '@/components/SvgIcon.vue'
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
  <SvgIcon class="sidebar-icon" :icon="icon" :size="size" :labelled="labelled" />
</template>

<style scoped>
.sidebar-icon {
  flex: none;
  color: var(--md-sys-color-on-surface-variant);
}
</style>
