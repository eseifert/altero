<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

/**
 * The grip between the sidebar and the item list.
 *
 * It draws nothing until it is wanted: a line in the gutter under the pointer,
 * and a lit one while it is being dragged or focused. The width it reports is
 * the parent's to keep -- this only says which way the pointer went.
 *
 * `role="separator"` with a `tabindex` is the pane splitter ARIA describes, and
 * the arrow keys that go with it are not a courtesy: a splitter that only a
 * pointer can move is a layout nobody on a keyboard can fix.
 */
const props = defineProps<{
  width: number
  min: number
  max: number
  /** What a double-click, and `Backspace`, put it back to. */
  preferred: number
}>()

const emit = defineEmits<{ 'update:width': [width: number] }>()

/** How far one arrow key moves it. Roughly one character of the sidebar. */
const STEP = 16

const dragging = ref(false)

function set(width: number): void {
  emit('update:width', Math.min(props.max, Math.max(props.min, Math.round(width))))
}

/*
 * The move and release listeners go on the window rather than on the grip, and
 * that is also why there is no pointer capture: a pointer dragged faster than
 * the layout follows leaves the element behind, and a release outside it would
 * otherwise never arrive and the drag would never end. `preventDefault` stops
 * the drag from selecting the sidebar's text on the way past.
 */
function startDrag(event: PointerEvent): void {
  if (event.button !== 0) return

  const originX = event.clientX
  const originWidth = props.width
  dragging.value = true

  const move = (moved: PointerEvent) => set(originWidth + moved.clientX - originX)
  const stop = () => {
    dragging.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
  }

  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
  event.preventDefault()
}

function onKeydown(event: KeyboardEvent): void {
  const moves: Record<string, number | undefined> = {
    ArrowLeft: props.width - STEP,
    ArrowRight: props.width + STEP,
    Home: props.min,
    End: props.max,
    Backspace: props.preferred,
  }

  const next = moves[event.key]
  if (next === undefined) return
  set(next)
  event.preventDefault()
}
</script>

<template>
  <div
    class="splitter"
    :class="{ 'splitter--dragging': dragging }"
    role="separator"
    tabindex="0"
    aria-orientation="vertical"
    :aria-label="t('Sidebar width')"
    :aria-valuenow="width"
    :aria-valuemin="min"
    :aria-valuemax="max"
    :title="t('Drag to resize the sidebar. Double-click to put it back.')"
    @pointerdown="startDrag"
    @keydown="onKeydown"
    @dblclick="set(preferred)"
  ></div>
</template>

<style scoped>
/*
 * Placed in the gap the grid already leaves rather than given a column of its
 * own, so the sidebar and the list stay exactly as far apart as they were and
 * the grip is centred between them. `--sidebar-width` is set on the grid and
 * inherits down to here.
 *
 * Full height, because the sidebar can be shorter than the list and a grip
 * that stopped where the tags do would be missing from most of the divide.
 */
.splitter {
  position: absolute;
  top: 0;
  bottom: 0;
  left: calc(var(--sidebar-width) + var(--md-spacing-4) / 2);
  width: 0.75rem;
  transform: translateX(-50%);
  /* A pointer that is about to drag horizontally must not also scroll. */
  touch-action: none;
  cursor: col-resize;
}

/* The line itself, drawn in the middle of the grab area. Absent until the
   pointer or the focus arrives: a permanent rule down the page would be one
   more thing to look at, and there is nothing to resize until somebody wants
   to. */
.splitter::before {
  content: '';
  display: block;
  width: 2px;
  height: 100%;
  margin: 0 auto;
  border-radius: 1px;
  background: var(--md-sys-color-outline-variant);
  opacity: 0;
  transition: opacity 120ms ease;
}

.splitter:hover::before,
.splitter:focus-visible::before,
.splitter--dragging::before {
  opacity: 1;
}

.splitter:focus-visible::before,
.splitter--dragging::before {
  background: var(--md-sys-color-primary);
}

.splitter:focus-visible {
  outline: none;
}

/* Below this the panes are stacked one above another, so there is no vertical
   divide to move. */
@media (max-width: 60rem) {
  .splitter {
    display: none;
  }
}
</style>
