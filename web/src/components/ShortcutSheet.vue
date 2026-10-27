<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { useModal } from '@/modal'

/**
 * What the keyboard does in the library, opened with `?`.
 *
 * Only what the interface really does: each line here is a key the item list
 * or the page answers. Keys are named as the keyboard in front of the reader
 * labels them -- Cmd on a Mac, and Strg, Entf or Pos1 where the catalogue
 * says so.
 */
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const dialog = useTemplateRef<HTMLDialogElement>('dialog')

useModal(dialog, () => emit('close'))

/** Apple's keyboards, whose command key does what Ctrl does elsewhere. */
const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)

const command = computed(() => (mac ? '⌘' : t('Ctrl')))

/** Each line: a modifier held, if any; the keys, any one of which does it; and what it does. */
const lines = computed<{ hold?: string; keys: string[]; what: string }[]>(() => [
  { keys: ['↑', '↓'], what: t('Previous or next item') },
  { keys: [t('Home'), t('End')], what: t('First or last item') },
  { keys: [t('Page Up'), t('Page Down')], what: t('Ten items up or down') },
  { hold: t('Shift'), keys: ['↑', '↓'], what: t('Extend the selection') },
  { hold: command.value, keys: ['↑', '↓'], what: t('Move without selecting') },
  { hold: command.value, keys: [t('Space')], what: t('Add to the selection or take out of it') },
  { hold: command.value, keys: ['A'], what: t('Select everything shown') },
  { keys: [t('Enter')], what: t('Show the item’s details') },
  { keys: ['F2'], what: t('Edit the title') },
  { keys: [t('Del')], what: t('Move to trash') },
  { keys: [t('Esc')], what: t('Clear the selection') },
  { keys: ['?'], what: t('Show keyboard shortcuts') },
])

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('close')
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog dialog--wide"
    :aria-label="t('Keyboard shortcuts')"
    @cancel.prevent="emit('close')"
    @click="backdrop"
  >
    <div class="dialog__body">
      <h2 class="dialog__title">{{ t('Keyboard shortcuts') }}</h2>
      <dl class="shortcuts">
        <template v-for="line in lines" :key="line.what">
          <dt class="shortcuts__keys">
            <kbd v-if="line.hold">{{ line.hold }}</kbd>
            <template v-for="(key, index) in line.keys" :key="key">
              <span v-if="index" class="shortcuts__or" aria-hidden="true">/</span>
              <kbd>{{ key }}</kbd>
            </template>
          </dt>
          <dd class="shortcuts__what">{{ line.what }}</dd>
        </template>
      </dl>
      <div class="dialog__actions">
        <AppButton @click="emit('close')">{{ t('Done') }}</AppButton>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.shortcuts {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.35rem var(--md-spacing-4);
  align-items: baseline;
  margin: 0;
}

.shortcuts__keys {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.3rem;
}

.shortcuts__or {
  color: var(--md-sys-color-on-surface-variant);
}

kbd {
  min-width: 1.4em;
  padding: 0.05rem 0.4rem;
  border: 1px solid var(--md-sys-color-outline);
  border-block-end-width: 2px;
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  font: inherit;
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
  text-align: center;
}

.shortcuts__what {
  margin: 0;
}

/* A narrow screen puts each line's keys above what they do. */
@media (max-width: 22rem) {
  .shortcuts {
    grid-template-columns: 1fr;
    gap: 0.15rem;
  }

  .shortcuts__what {
    margin-block-end: 0.4rem;
  }
}
</style>
