<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/**
 * What the right-hand pane says when more than one row is picked out.
 *
 * Not a detail pane for several items. An item's fields belong to that item,
 * and five items' fields side by side would be five panes in the space of one;
 * what several rows have in common is not what they say but what can be done to
 * them. So this is a count and the errands, in the same words the detail pane
 * uses for one — a reader who has learnt "Move or copy…" on one row should not
 * meet a different phrase for the same thing on three.
 *
 * There is no field editor here for the same reason there is none there: this
 * interface does not edit items. Publishing is missing too, and that is not an
 * omission — the wizard's questions are about the item in front of it, so a
 * selection has no single set of answers to give it.
 */
defineProps<{
  /** How many rows are picked out. */
  count: number
  /** Whether the server says this account may change the library. */
  writable: boolean
  /** Whether every one of them is already in the trash, which is what decides
   *  between throwing away and deleting for good. */
  trashed: boolean
}>()

const emit = defineEmits<{
  move: []
  trash: []
  restore: []
  remove: []
  close: []
}>()

const { t } = useI18n()
</script>

<template>
  <article class="selection">
    <header class="selection__header">
      <h2 class="selection__count">
        {{ t('{count} item selected | {count} items selected', count) }}
      </h2>
      <button
        class="selection__close"
        type="button"
        :aria-label="t('Clear the selection')"
        @click="emit('close')"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </header>

    <!-- The same errands as a drag, in the same words the detail pane uses for
         one row. Only where the server says the library can be written to. -->
    <div v-if="writable" class="selection__tools">
      <button class="selection__tool" type="button" @click="emit('move')">
        {{ t('Move or copy…') }}
      </button>
      <button v-if="!trashed" class="selection__tool" type="button" @click="emit('trash')">
        {{ t('Move to trash') }}
      </button>
      <template v-else>
        <button class="selection__tool" type="button" @click="emit('restore')">
          {{ t('Restore to Library') }}
        </button>
        <button
          class="selection__tool selection__tool--danger"
          type="button"
          @click="emit('remove')"
        >
          {{ t('Delete') }}
        </button>
      </template>
    </div>

  </article>
</template>

<style scoped>
.selection {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  padding: var(--md-spacing-4);
  align-items: flex-start;
}

.selection__header {
  display: flex;
  align-items: flex-start;
  gap: var(--md-spacing-3);
  width: 100%;
}

.selection__count {
  flex: 1;
  min-width: 0;
  margin: 0;
  font-size: var(--md-sys-typescale-title-medium-size, 1.05rem);
  line-height: 1.35;
}

.selection__close {
  display: grid;
  flex: none;
  place-items: center;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.selection__close:hover {
  background: var(--md-sys-state-hover-surface);
}

.selection__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--md-spacing-2);
}

.selection__tool {
  padding: 0.25rem 0.7rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: 999px;
  background: none;
  color: inherit;
  font: inherit;
  font-size: var(--md-sys-typescale-body-medium-size);
  cursor: pointer;
}

.selection__tool:hover {
  background: var(--md-sys-state-hover-surface);
}

.selection__tool--danger {
  border-color: var(--md-sys-color-error);
  color: var(--md-sys-color-error);
}

/* A finger cannot hit a 28-pixel target reliably, and nothing here is revealed
   by hovering, so the controls simply grow where the pointer is coarse. */
@media (pointer: coarse) {
  .selection__close {
    width: 2.5rem;
    height: 2.5rem;
  }

  .selection__tool {
    padding: 0.55rem 1rem;
  }
}
</style>
