<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

/**
 * The grip between two panes.
 *
 * It draws nothing until it is wanted: a line in the gutter under the pointer,
 * and a lit one while it is being dragged or focused. The width it reports is
 * the parent's to keep -- this only says which way the pointer went -- and
 * where it sits is the parent's too, because only the layout knows which gutter
 * this is.
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
  /** What the grip is called, since a window can hold more than one. */
  label: string
  /**
   * Whether the pane being sized is to the *right* of the grip.
   *
   * The detail pane is, and it therefore grows as the pointer goes left. Both
   * grips still move the same way under the same key: the arrow keys move the
   * grip, not the pane, so `ArrowRight` always moves the divide rightwards.
   */
  trailing?: boolean
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

  const move = (moved: PointerEvent) =>
    set(originWidth + (props.trailing ? originX - moved.clientX : moved.clientX - originX))
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
  const towards = (grip: number) => (props.trailing ? -grip : grip)
  const moves: Record<string, number | undefined> = {
    ArrowLeft: props.width + towards(-STEP),
    ArrowRight: props.width + towards(STEP),
    Home: props.trailing ? props.max : props.min,
    End: props.trailing ? props.min : props.max,
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
    :aria-label="label"
    :aria-valuenow="width"
    :aria-valuemin="min"
    :aria-valuemax="max"
    :title="t('Drag to move this divide. Double-click to put it back.')"
    @pointerdown="startDrag"
    @keydown="onKeydown"
    @dblclick="set(preferred)"
  ></div>
</template>

<style scoped>
/*
 * Everything except where it is. The grip is placed by whoever draws the
 * layout, in the gap the grid already leaves, so the panes stay exactly as far
 * apart as they were.
 *
 * A fingertip is about ten times the area of a pointer tip, so on a touch
 * screen the grab area widens -- the line it draws does not.
 */
.splitter {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 0.75rem;
  transform: translateX(-50%);
  /* A pointer that is about to drag horizontally must not also scroll. */
  touch-action: none;
  cursor: col-resize;
}

@media (pointer: coarse) {
  .splitter {
    width: 1.75rem;
  }
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
</style>
