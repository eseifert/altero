<script setup lang="ts">
import { ref } from 'vue'

import SidebarIcon from '@/components/SidebarIcon.vue'
import type { CollectionNode } from '@/stores/library'

/**
 * One level of the collection tree, recursing into itself.
 *
 * Expansion is local state rather than something the store holds: which
 * branches a person has opened is a property of this view, and moving it into
 * the store would mean rebuilding it every time the library reloads.
 */
defineProps<{ nodes: CollectionNode[]; selected: string | null; depth?: number }>()

const emit = defineEmits<{ select: [key: string] }>()

const expanded = ref<Set<string>>(new Set())

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
      <div class="tree__row" :style="{ paddingLeft: `${(depth ?? 0) * 0.9 + 0.5}rem` }">
        <button
          v-if="node.children.length"
          class="tree__twisty"
          type="button"
          :aria-label="expanded.has(node.key) ? 'Collapse' : 'Expand'"
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
        >
          <SidebarIcon name="collection" />
          <span class="tree__label">{{ node.data.name }}</span>
          <span v-if="node.meta.numItems" class="tree__count">{{ node.meta.numItems }}</span>
        </button>
      </div>

      <CollectionTree
        v-if="node.children.length && expanded.has(node.key)"
        :nodes="node.children"
        :selected="selected"
        :depth="(depth ?? 0) + 1"
        @select="emit('select', $event)"
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
}

.tree__twisty {
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
  padding: 0.3rem 0.5rem;
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
</style>
