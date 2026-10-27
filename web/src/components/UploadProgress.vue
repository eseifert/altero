<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import { formatBytes } from '@/formats'
import { useUploadStore } from '@/stores/uploads'

/*
 * Files on their way up, each with a bar, and the ones that did not make it.
 *
 * In a corner of the page rather than in a pane, because an upload is not
 * about what is on screen: a file dropped on a collection is still going after
 * the reader has moved on. A bar is a `<progress>`, which a screen reader
 * reads with its name and value when it is reached; a failure is an alert,
 * since it is the one thing here the reader has to know without looking.
 */

const { t } = useI18n()
const store = useUploadStore()
</script>

<template>
  <section v-if="store.uploads.length" class="menu uploads" :aria-label="t('Uploads')">
    <ul class="uploads__list">
      <li v-for="entry in store.uploads" :key="entry.id" class="uploads__entry">
        <div class="uploads__text">
          <span class="uploads__name" dir="auto">{{ entry.name }}</span>
          <span v-if="!entry.error" class="uploads__size">
            {{ formatBytes(entry.sent) }} / {{ formatBytes(entry.total) }}
          </span>
          <span v-else class="uploads__error" role="alert">{{ entry.error }}</span>
          <progress
            v-if="!entry.error"
            class="uploads__bar"
            :value="entry.sent"
            :max="entry.total || 1"
            :aria-label="t('Uploading {name}', { name: entry.name })"
          ></progress>
        </div>
        <button
          v-if="!entry.error"
          class="icon-button uploads__button"
          type="button"
          :aria-label="t('Cancel upload of {name}', { name: entry.name })"
          :title="t('Cancel')"
          @click="store.cancel(entry.id)"
        >
          <AppIcon name="close" :size="20" />
        </button>
        <button
          v-else
          class="icon-button uploads__button"
          type="button"
          :aria-label="t('Dismiss')"
          :title="t('Dismiss')"
          @click="store.dismiss(entry.id)"
        >
          <AppIcon name="close" :size="20" />
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
@import '@/styles/surfaces.css';

/* A floating surface, drawn as the menus are; placed in a corner of the
   window rather than under a button, with the formatting bar's quieter edge. */
.menu.uploads {
  position: fixed;
  inset-inline-end: max(var(--md-spacing-4), env(safe-area-inset-right));
  inset-block-end: max(var(--md-spacing-4), env(safe-area-inset-bottom));
  z-index: 90;
  inline-size: min(calc(100vw - 2 * var(--md-spacing-4)), 22rem);
  max-block-size: 40vh;
  overflow-y: auto;
  padding: 0;
  border-color: var(--md-sys-color-outline-variant);
}

.uploads__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: var(--md-spacing-1);
  list-style: none;
}

.uploads__entry {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  padding: var(--md-spacing-2);
}

.uploads__text {
  display: grid;
  flex: 1;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.2rem var(--md-spacing-2);
  min-inline-size: 0;
}

.uploads__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.uploads__size {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
  font-variant-numeric: tabular-nums;
}

.uploads__error {
  grid-column: 1 / -1;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}

.uploads__bar {
  grid-column: 1 / -1;
  inline-size: 100%;
  block-size: 4px;
  accent-color: var(--md-sys-color-primary);
}

.uploads__button {
  flex: none;
  border-radius: var(--md-sys-shape-corner-small);
}

@media (pointer: coarse) {
  .uploads__button {
    width: 2.5rem;
    height: 2.5rem;
  }
}
</style>
