<script setup lang="ts">
/**
 * Something that appears in place — a dialog, a menu — fading in from slightly
 * smaller, and leaving the same way. The classes are in `styles/motion.css`.
 */
const emit = defineEmits<{ beforeLeave: [element: Element]; afterLeave: [element: Element] }>()
</script>

<template>
  <Transition
    name="fade-scale"
    appear
    @before-leave="emit('beforeLeave', $event)"
    @after-leave="emit('afterLeave', $event)"
  >
    <slot />
  </Transition>
</template>
