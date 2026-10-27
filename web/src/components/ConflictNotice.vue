<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/*
 * Both versions of something two people changed at once, and a choice.
 *
 * Drawn where the edit was made, under the field or the creators, once a save
 * has found that somebody else changed the same thing first. The words are
 * the desktop's own for its conflict window: the local version is what was
 * typed here, the remote one what is stored. Neither is written until one is
 * chosen, and choosing the remote one writes nothing at all -- it is what the
 * pane already shows.
 */

const { t } = useI18n()

defineProps<{
  /** An id unique on the page, which each choice is described by. */
  id: string
  mine: string
  theirs: string
}>()

const emit = defineEmits<{ mine: []; theirs: [] }>()
</script>

<template>
  <div class="conflict" role="alert">
    <p class="conflict__message">{{ t('Changed elsewhere while you were editing.') }}</p>
    <div class="conflict__version">
      <span :id="`${id}-mine`" class="conflict__value" dir="auto">{{
        t('Local version: {value}', { value: mine || t('(empty)') })
      }}</span>
      <button class="conflict__choose" type="button" :aria-describedby="`${id}-mine`" @click="emit('mine')">
        {{ t('Choose this version') }}
      </button>
    </div>
    <div class="conflict__version">
      <span :id="`${id}-theirs`" class="conflict__value" dir="auto">{{
        t('Remote version: {value}', { value: theirs || t('(empty)') })
      }}</span>
      <button class="conflict__choose" type="button" :aria-describedby="`${id}-theirs`" @click="emit('theirs')">
        {{ t('Choose this version') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.conflict {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-block-start: 0.3rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--md-sys-color-outline);
  border-inline-start: 3px solid var(--md-sys-color-error);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}

.conflict__message {
  margin: 0;
  color: var(--md-sys-color-error);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.conflict__version {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.2rem var(--md-spacing-2);
}

.conflict__value {
  flex: 1 1 12rem;
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.conflict__choose {
  flex: none;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-primary);
  font: inherit;
  cursor: pointer;
}

.conflict__choose:hover {
  background: var(--md-sys-state-hover-surface);
}

@media (pointer: coarse) {
  .conflict__choose {
    min-height: 2.25rem;
  }
}
</style>
