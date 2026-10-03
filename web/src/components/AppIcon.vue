<script setup lang="ts">
import { CONTROL_ICONS } from '@/icons'
import SvgIcon from './SvgIcon.vue'

withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
</script>

<template>
  <SvgIcon :icon="CONTROL_ICONS[name]" :size="size" />
</template>
