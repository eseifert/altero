<script setup lang="ts">
import type { SvgIcon } from '@/icons'

withDefaults(defineProps<{ icon: SvgIcon; size?: number; labelled?: boolean }>(), {
  size: 24,
  labelled: false,
})
</script>

<template>
  <svg
    v-bind="icon.attributes"
    :width="size"
    :height="size"
    :role="labelled ? 'img' : 'presentation'"
    :aria-hidden="labelled ? undefined : 'true'"
    :aria-label="labelled ? icon.label : undefined"
    focusable="false"
  >
    <title v-if="labelled">{{ icon.label }}</title>
    <g v-html="icon.markup" />
  </svg>
</template>

<style scoped>
/* Independent scale preserves the tree twisty's open/closed rotation. */
svg[data-mirror-rtl]:dir(rtl) {
  scale: -1 1;
}
</style>
