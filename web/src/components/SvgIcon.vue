<script setup lang="ts">
import type { SvgIcon } from '@/icons'

withDefaults(defineProps<{ icon: SvgIcon; size?: number; labelled?: boolean }>(), {
  size: 20,
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
