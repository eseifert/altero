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
/* Compose the mirror after rotation without independent transforms or :dir(),
   which are newer than the supported Safari/Chromium targets. */
svg[data-mirror-rtl] {
  transform: scaleX(var(--icon-scale, 1)) rotate(var(--icon-angle, 0deg));
}

[dir='rtl'] svg[data-mirror-rtl] {
  --icon-scale: -1;
}
</style>
