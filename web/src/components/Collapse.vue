<script setup lang="ts">
/**
 * A section that opens and closes by its height.
 *
 * CSS cannot transition to `height: auto`, so the height is measured: set to
 * what the content needs for the length of the transition, and let go of
 * afterwards so the section can still grow and shrink with what it holds.
 * The heights are set through the CSSOM, which the Content-Security-Policy
 * leaves alone where a `style` attribute would not be.
 */
function open(element: Element): void {
  const section = element as HTMLElement
  section.style.height = '0'
  void section.offsetHeight // Commit the start before asking for the end.
  section.style.height = `${section.scrollHeight}px`
}

function close(element: Element): void {
  const section = element as HTMLElement
  section.style.height = `${section.scrollHeight}px`
  void section.offsetHeight
  section.style.height = '0'
}

function release(element: Element): void {
  ;(element as HTMLElement).style.height = ''
}
</script>

<template>
  <Transition
    name="collapse"
    @enter="open"
    @after-enter="release"
    @leave="close"
    @after-leave="release"
  >
    <slot />
  </Transition>
</template>
