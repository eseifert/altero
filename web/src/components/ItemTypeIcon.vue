<script setup lang="ts">
import { computed } from 'vue'

import { iconFor } from '@/items/icons'

const props = withDefaults(defineProps<{ itemType: string; size?: number }>(), { size: 20 })

const icon = computed(() => iconFor(props.itemType))
</script>

<template>
  <svg
    class="item-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    role="img"
    :aria-label="icon.label"
  >
    <title>{{ icon.label }}</title>
    <path v-for="(d, index) in icon.paths" :key="index" :d="d" />
  </svg>
</template>

<style scoped>
.item-icon {
  flex: none;
  color: var(--md-sys-color-on-surface-variant);
}
</style>
