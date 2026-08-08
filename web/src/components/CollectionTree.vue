<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SidebarIcon from '@/components/SidebarIcon.vue'
import type { CollectionNode } from '@/stores/library'

const { t } = useI18n()

/**
 * One level of the collection tree, recursing into itself.
 *
 * Expansion is local state rather than something the store holds: which
 * branches a person has opened is a property of this view, and moving it into
 * the store would mean rebuilding it every time the library reloads.
 */
const props = defineProps<{
  nodes: CollectionNode[]
  selected: string | null
  depth?: number
  /** Whether to offer the controls that change the tree. Off for a library
   *  this account may only read, which the server decides. */
  editable?: boolean
  /** Whether an item is being dragged, and could be dropped on a row here. */
  dragging?: boolean
  /** The row a drag is over, as the view names it, so one row lights up. */
  over?: string | null
}>()

const emit = defineEmits<{
  select: [key: string]
  add: [node: CollectionNode]
  settings: [node: CollectionNode]
  /** `Delete` on a row, which asks the same question the dialog's Delete does. */
  remove: [node: CollectionNode]
  over: [move: { target: string; event: DragEvent }]
  leave: [target: string]
  drop: [dropped: { node: CollectionNode; event: DragEvent }]
}>()

/** How the view names this row while something is being dragged over it. */
function target(node: CollectionNode): string {
  return `collection:${node.key}`
}

const expanded = ref<Set<string>>(new Set())

/** Whether ``node`` or anything under it is ``key``. */
function holds(node: CollectionNode, key: string): boolean {
  return node.key === key || node.children.some((child) => holds(child, key))
}

/*
 * Open the branch the selection is in.
 *
 * A collection can be selected by something other than a click on its row --
 * making one inside a collapsed parent selects it, and so would a link into the
 * tree -- and a selection nobody can see is worse than no selection at all.
 * Each level opens only its own node; the level below mounts with the selection
 * already set and does the same, so the chain unfolds one step at a time.
 *
 * It stays a normal expansion, so it can be collapsed again afterwards.
 */
watch(
  () => props.selected,
  (key) => {
    if (!key) return
    const containing = props.nodes.filter((node) => node.children.length && holds(node, key))
    if (containing.length) {
      expanded.value = new Set([...expanded.value, ...containing.map((node) => node.key)])
    }
  },
  { immediate: true },
)

function toggle(key: string): void {
  const next = new Set(expanded.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expanded.value = next
}
</script>

<template>
  <ul class="tree" role="group">
    <li v-for="node in nodes" :key="node.key">
      <!--
        Dropping an item here files it in this collection. Adding rather than
        moving, which is Zotero's rule; holding Shift while dropping takes it
        out of the collection being shown, which is what makes it a move.
      -->
      <div
        class="tree__row"
        :class="{ 'tree__row--over': dragging && over === target(node) }"
        :style="{ paddingLeft: `${(depth ?? 0) * 0.9 + 0.15}rem` }"
        @dragover="emit('over', { target: target(node), event: $event })"
        @dragleave="emit('leave', target(node))"
        @drop.prevent="emit('drop', { node, event: $event })"
      >
        <button
          v-if="node.children.length"
          class="tree__twisty"
          type="button"
          :aria-label="expanded.has(node.key) ? t('Collapse') : t('Expand')"
          :aria-expanded="expanded.has(node.key)"
          @click="toggle(node.key)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
               :class="['tree__chevron', { 'tree__chevron--open': expanded.has(node.key) }]">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
        <span v-else class="tree__twisty tree__twisty--empty" aria-hidden="true"></span>

        <button
          type="button"
          :class="['tree__name', { 'tree__name--selected': selected === node.key }]"
          :aria-current="selected === node.key ? 'true' : undefined"
          @click="emit('select', node.key)"
          @keydown.delete.prevent="editable && emit('remove', node)"
        >
          <SidebarIcon name="collection" />
          <span class="tree__label">{{ node.data.name }}</span>
          <span v-if="node.meta.numItems" class="tree__count">{{ node.meta.numItems }}</span>
        </button>

        <!--
          Two controls, and the pencil is the one that leads everywhere else:
          renaming, moving and deleting are all this collection's settings, and
          a row has room for a pair of icons rather than a menu of them. The
          plus is beside it because it makes a *different* collection, which is
          not a setting of this one.

          Kept in the document rather than shown on hover alone: a control that
          exists only under a pointer is a control a keyboard cannot reach.
          What hovering and focusing change is whether they are drawn, not
          whether they are there.
        -->
        <span v-if="editable" class="tree__actions">
          <button
            class="tree__action"
            type="button"
            :aria-label="t('New subcollection inside “{name}”', { name: node.data.name })"
            :title="t('New subcollection inside “{name}”', { name: node.data.name })"
            @click="emit('add', node)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
          <button
            class="tree__action"
            type="button"
            :aria-label="t('Settings for “{name}”', { name: node.data.name })"
            :title="t('Settings for “{name}”', { name: node.data.name })"
            @click="emit('settings', node)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M4 20h4L19 9a2.8 2.8 0 10-4-4L4 16z" />
            </svg>
          </button>
        </span>
      </div>

      <CollectionTree
        v-if="node.children.length && expanded.has(node.key)"
        :nodes="node.children"
        :selected="selected"
        :depth="(depth ?? 0) + 1"
        :editable="editable"
        :dragging="dragging"
        :over="over"
        @select="emit('select', $event)"
        @add="emit('add', $event)"
        @settings="emit('settings', $event)"
        @remove="emit('remove', $event)"
        @over="emit('over', $event)"
        @leave="emit('leave', $event)"
        @drop="emit('drop', $event)"
      />
    </li>
  </ul>
</template>

<style scoped>
.tree {
  margin: 0;
  padding: 0;
  list-style: none;
}

.tree__row {
  display: flex;
  align-items: center;
  gap: 0.15rem;
  border-radius: var(--md-sys-shape-corner-small);
}

/* An outline rather than a fill, so a row being dragged over does not look
   like the row that is selected. */
.tree__row--over {
  outline: 2px solid var(--md-sys-color-primary);
  outline-offset: -1px;
}

.tree__twisty {
  display: grid;
  place-items: center;
  width: 1rem;
  height: 1.25rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.tree__twisty--empty {
  cursor: default;
}

.tree__chevron {
  transition: transform 120ms ease;
}

.tree__chevron--open {
  transform: rotate(90deg);
}

.tree__name {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--md-spacing-2);
  min-width: 0;
  padding: 0.3rem 0.4rem;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.tree__name:hover {
  background: var(--md-sys-color-surface-container-high);
}

.tree__name--selected {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.tree__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree__count {
  margin-left: auto;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-label-small-size, 0.75rem);
}

/* Transparent rather than absent, so the row does not change width when the
   pointer arrives and the names below it do not shift sideways. */
.tree__actions {
  display: flex;
  flex: none;
  gap: 0.1rem;
  opacity: 0;
  transition: opacity 120ms ease;
}

.tree__row:hover .tree__actions,
.tree__row:focus-within .tree__actions {
  opacity: 1;
}

.tree__action {
  display: grid;
  place-items: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.tree__action:hover {
  background: var(--md-sys-color-surface-container-highest);
  color: var(--md-sys-color-on-surface);
}

/* Coarse pointers have no hover to reveal anything with, and a phone showing
   the sidebar is showing the whole of it. */
@media (hover: none) {
  .tree__actions {
    opacity: 1;
  }
}
</style>
