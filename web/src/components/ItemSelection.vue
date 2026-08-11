<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import SidebarIcon from '@/components/SidebarIcon.vue'

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
 * selection has no single set of answers to give it. Writing the rows out as a
 * file is here, and is the one errand that is not a write, so it appears in a
 * library this account may only read.
 */
defineProps<{
  /** How many rows are picked out. */
  count: number
  /** Whether the server says this account may change the library. */
  writable: boolean
  /** Whether every one of them is already in the trash, which is what decides
   *  between throwing away and deleting for good. */
  trashed: boolean
  /** Whether any of them has a bibliography entry to write out. */
  exportable?: boolean
}>()

const emit = defineEmits<{
  move: []
  trash: []
  restore: []
  remove: []
  export: []
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
        class="icon-button selection__close"
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

    <!-- The same errands as a drag, and the same glyphs the detail pane draws
         for one row: three rows picked out do not make trashing them a
         different errand. Writing them out is not a write, so it is offered in
         a library this account may only read. -->
    <div v-if="writable || exportable" class="selection__tools toolbar">
      <template v-if="writable">
        <button
          class="icon-button"
          type="button"
          :aria-label="t('Move or copy…')"
          :title="t('Move or copy…')"
          @click="emit('move')"
        >
          <SidebarIcon name="move" :size="18" />
        </button>
        <button
          v-if="!trashed"
          class="icon-button"
          type="button"
          :aria-label="t('Move to trash')"
          :title="t('Move to trash')"
          @click="emit('trash')"
        >
          <SidebarIcon name="trash" :size="18" />
        </button>
        <template v-else>
          <button
            class="icon-button"
            type="button"
            :aria-label="t('Restore to Library')"
            :title="t('Restore to Library')"
            @click="emit('restore')"
          >
            <SidebarIcon name="restore" :size="18" />
          </button>
          <button
            class="icon-button icon-button--danger"
            type="button"
            :aria-label="t('Delete')"
            :title="t('Delete')"
            @click="emit('remove')"
          >
            <SidebarIcon name="deleteforever" :size="18" />
          </button>
        </template>
      </template>

      <button
        v-if="exportable"
        class="icon-button"
        type="button"
        :aria-label="t('Export…')"
        :title="t('Export…')"
        @click="emit('export')"
      >
        <SidebarIcon name="export" :size="18" />
      </button>
    </div>

  </article>
</template>

<style scoped>
@import '@/styles/surfaces.css';

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

/* The close is an icon button standing on its own rather than in the toolbar:
   it dismisses the pane instead of acting on what is in it. */
.selection__close {
  border-radius: var(--md-sys-shape-corner-small);
}

/* The toolbar's own row, plus the wrapping a narrow pane needs. */
.selection__tools {
  flex-wrap: wrap;
}

/* A finger cannot hit a 28-pixel target reliably, and nothing here is revealed
   by hovering, so the controls simply grow where the pointer is coarse. */
@media (pointer: coarse) {
  .selection__close {
    width: 2.5rem;
    height: 2.5rem;
  }

}
</style>
