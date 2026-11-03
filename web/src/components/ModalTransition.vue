<script setup lang="ts">
import FadeScale from '@/components/FadeScale.vue'
import { finishModalLeave, startModalLeave } from '@/modal'

// Keep the native top layer (or fallback trap) until Vue removes the dialog.
// The content remains mounted only while open, so every opening starts fresh.
</script>

<template>
  <FadeScale @before-leave="startModalLeave" @after-leave="finishModalLeave">
    <slot />
  </FadeScale>
</template>
