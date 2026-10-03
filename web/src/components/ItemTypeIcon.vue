<script setup lang="ts">
import { computed } from 'vue'

import SvgIcon from '@/components/SvgIcon.vue'
import { iconFor } from '@/items/icons'

const props = withDefaults(defineProps<{ itemType: string; size?: number }>(), { size: 20 })

const icon = computed(() => iconFor(props.itemType))
</script>

<template>
  <SvgIcon class="item-icon" :icon="icon" :size="size" :labelled="true" />
</template>

<style scoped>
.item-icon {
  flex: none;
  color: var(--md-sys-color-on-surface-variant);
}
</style>
