<script setup lang="ts">
import { retire, revive } from '@/retiring'

/**
 * A section that opens and closes by its height.
 *
 * Supporting browsers interpolate between zero and `auto` in motion.css.
 * Others measure the height for the transition, then release it so nested
 * sections can grow freely. Those heights use the CSSOM for CSP compatibility.
 */
function intrinsic(): boolean {
  return globalThis.CSS?.supports?.('interpolate-size', 'allow-keywords') ?? false
}

function open(element: Element): void {
  if (intrinsic()) return
  const section = element as HTMLElement
  section.style.height = '0'
  void section.offsetHeight // Commit the start before asking for the end.
  section.style.height = `${section.scrollHeight}px`
}

function close(element: Element): void {
  const section = element as HTMLElement
  if (!intrinsic()) {
    // Start at what is currently drawn, including an interrupted opening.
    section.style.height = `${section.getBoundingClientRect().height}px`
    void section.offsetHeight
    section.style.height = '0'
  }
  retire(section)
}

function release(element: Element): void {
  ;(element as HTMLElement).style.height = ''
  revive(element)
}
</script>

<template>
  <Transition
    name="collapse"
    @enter="open"
    @after-enter="release"
    @leave="close"
    @after-leave="release"
    @leave-cancelled="release"
  >
    <slot />
  </Transition>
</template>
