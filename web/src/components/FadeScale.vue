<script setup lang="ts">
/**
 * Something that appears in place — a dialog, a menu — fading in from slightly
 * smaller, and leaving the same way. The classes are in `styles/motion.css`.
 */
</script>

<template>
  <Transition name="fade-scale" appear>
    <slot />
  </Transition>
</template>
