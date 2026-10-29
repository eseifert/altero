<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import { getItemTitle } from '@/items/titles'
import type { ItemEnvelope } from '@/stores/library'

const props = withDefaults(defineProps<{
  items: ItemEnvelope[]
  groups: string[][]
  selection: string[]
  master?: string | null
  tabKey: string | null
  carried?: string[]
  fileTarget?: string | null
  takesFiles?: (item: ItemEnvelope) => boolean
}>(), { master: null, carried: () => [], fileTarget: null })
const emit = defineEmits<{
  select: [item: ItemEnvelope]
  inspect: [item: ItemEnvelope]
  focus: [key: string]
  carry: [item: ItemEnvelope, event: PointerEvent]
  remove: [item: ItemEnvelope]
  keydown: [event: KeyboardEvent]
}>()
const { t } = useI18n()
const selected = computed(() => new Set(props.selection))
const shown = computed(() => {
  const rows = new Map(props.items.map((item) => [item.key, item]))
  return props.groups.map((keys) => {
    const ordered = props.master && keys.includes(props.master)
      ? [props.master, ...keys.filter((key) => key !== props.master)] : keys
    return ordered.map((key) => rows.get(key)).filter((item): item is ItemEnvelope => Boolean(item))
  }).filter((group) => group.length > 0)
})
</script>

<template>
  <ul class="duplicate-groups" :aria-label="t('Duplicate Items')" @keydown="emit('keydown', $event)">
    <li v-for="group in shown" :key="[...group.map((item) => item.key)].sort().join(',')" class="duplicate-group pane">
      <ul class="duplicate-group__members" :aria-label="getItemTitle(group[0]!) || t('(untitled)')">
        <li v-for="(item, index) in group" :key="item.key" class="duplicate-group__line">
          <button
            type="button"
            class="duplicate-group__row"
            :class="{ 'row--current': selected.has(item.key), 'duplicate-group__row--carried': carried.includes(item.key), 'duplicate-group__row--over': fileTarget === `item:${item.key}` }"
            :aria-pressed="selected.has(item.key)"
            :data-row="item.key"
            :data-file-drop="takesFiles?.(item) ? `item:${item.key}` : undefined"
            :tabindex="item.key === tabKey ? 0 : -1"
            @focus="emit('focus', item.key)"
            @click="emit('select', item)"
            @pointerdown="emit('carry', item, $event)"
            @keydown.f2.prevent.stop="emit('inspect', item)"
            @keydown.delete.prevent="emit('remove', item)"
          >
            <ItemTypeIcon :item-type="item.data.itemType" />
            <span class="duplicate-group__title">
              <span dir="auto">{{ getItemTitle(item) || t('(untitled)') }}</span>
              <small v-if="index === 0" class="duplicate-group__master">{{ t('Master item') }}</small>
            </span>
            <span class="duplicate-group__creator" dir="auto">{{ item.meta.creatorSummary ?? '' }}</span>
            <span class="duplicate-group__date">{{ item.meta.parsedDate ?? '' }}</span>
          </button>
        </li>
      </ul>
    </li>
  </ul>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.duplicate-groups, .duplicate-group__members {
  margin: 0;
  padding: 0;
  list-style: none;
}

.duplicate-groups {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding-block-start: var(--md-spacing-3);
}

.duplicate-group {
  overflow: hidden;
}

.duplicate-group__row {
  display: grid;
  grid-template-columns: auto minmax(7rem, 2fr) minmax(0, 1fr) minmax(0, 7rem);
  align-items: center;
  gap: var(--md-spacing-3);
  inline-size: 100%;
  min-block-size: 36px;
  padding: var(--md-spacing-2) var(--md-spacing-4);
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
  cursor: pointer;
  user-select: none;
  -webkit-touch-callout: none;
}

.duplicate-group__row:hover {
  background: var(--md-sys-state-hover-surface);
}

.duplicate-group__row[aria-pressed='true'] {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.duplicate-group__row--carried {
  opacity: 0.5;
}

.duplicate-group__title {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  min-inline-size: 0;
}

.duplicate-group__row--over {
  outline: 2px solid var(--md-sys-color-primary);
  outline-offset: -2px;
}

.duplicate-group__title > span {
  inline-size: 100%;
}


.duplicate-group__title > span, .duplicate-group__creator, .duplicate-group__date {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.duplicate-group__master {
  flex-shrink: 0;
  font-size: var(--md-sys-typescale-body-small-size);
  font-weight: 500;
  color: var(--md-sys-color-on-surface-variant);
}

.duplicate-group__line:first-child .duplicate-group__title > span {
  font-weight: 500;
}

@media (max-width: 700px) {
  .duplicate-group__row {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .duplicate-group__creator, .duplicate-group__date {
    display: none;
  }
}

@media (pointer: coarse) {
  .duplicate-group__row {
    min-block-size: 44px;
  }
}
</style>
