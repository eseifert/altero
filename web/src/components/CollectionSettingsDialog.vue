<script setup lang="ts">
import { onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import type { Place } from '@/collectionplaces'

/**
 * What a collection is called and where it sits.
 *
 * The two are one dialog because they are one thought — this collection's
 * settings — and because the sidebar has room for one control per row, not
 * three. The row's pencil opens this; the row's plus still makes a
 * subcollection, which is a different collection and not a setting of this one.
 *
 * Moving is a picker rather than a drag: a tree can be taller than the window,
 * and a collection cannot be dropped on a parent that is scrolled out of sight.
 * Items are dragged; a collection is moved by naming where it goes.
 *
 * The list of places is `collectionplaces.ts`'s to compute, because it is the
 * tree flattened and the tree is the view's. What it must not contain is this
 * collection or anything under it: a collection inside itself is a branch
 * nothing can reach any more, and the server refuses it — the picker simply
 * never offers it.
 */
const props = defineProps<{
  name: string
  parentKey: string | null
  places: Place[]
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  submit: [changes: { name: string; parentCollection: string | null }]
  remove: []
  cancel: []
}>()

const { t } = useI18n()

/* Seeded from what is stored, so the dialog opens showing the collection as it
   is and Save without an edit is a no-op the reader can see is a no-op. */
const name = ref(props.name)
const parentKey = ref(props.parentKey)

const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const field = useTemplateRef<HTMLInputElement>('field')

onMounted(() => {
  dialog.value?.showModal()
  field.value?.focus()
  /* Renaming is the common errand, and a name that arrives selected is one
     keystroke from being replaced and one arrow key from being edited. */
  field.value?.select()
})

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('cancel')
}

function submit(): void {
  /* `?? null` because the library's own option carries no key, and a select
     that has been through the DOM can hand back an absent value rather than
     the null it was given. Absent means "leave the parent alone" to the
     server, which is the opposite of what picking the library asks for. */
  emit('submit', { name: name.value.trim(), parentCollection: parentKey.value ?? null })
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog"
    :aria-label="t('Settings for “{name}”', { name: props.name })"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <form class="dialog__body" @submit.prevent="submit">
      <h2 class="dialog__title">{{ t('Collection settings') }}</h2>

      <label class="dialog__label" for="collection-settings-name">{{ t('Name') }}</label>
      <input
        id="collection-settings-name"
        ref="field"
        v-model="name"
        class="dialog__field"
        type="text"
        autocomplete="off"
        :disabled="busy"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="error ? 'collection-settings-error' : undefined"
      />

      <label class="dialog__label" for="collection-settings-parent">{{ t('Inside') }}</label>
      <!--
        The indent is written into the label rather than left to CSS, because
        `option` is drawn by the platform and takes almost no styling. Figure
        spaces rather than a border or a dash: they read as an indent to the
        eye and as nothing much to a screen reader, which gets the name.
      -->
      <select
        id="collection-settings-parent"
        v-model="parentKey"
        class="dialog__field"
        :disabled="busy"
      >
        <option v-for="place in places" :key="place.key ?? ''" :value="place.key">
          {{ ' '.repeat(place.depth * 2) + place.label }}
        </option>
      </select>

      <p v-if="error" id="collection-settings-error" class="dialog__error" role="alert">
        {{ error }}
      </p>

      <!--
        Deleting sits apart from the pair that save, on the other side of the
        row: it is the one control here that cannot be undone by pressing the
        other one. What it does is ask — the confirmation is in the sidebar,
        under the collection it is about, where the tree can still be seen.
      -->
      <div class="dialog__actions">
        <AppButton variant="text" class="dialog__danger" :disabled="busy" @click="emit('remove')">
          {{ t('Delete') }}
        </AppButton>
        <span class="dialog__spacer"></span>
        <AppButton variant="text" :disabled="busy" @click="emit('cancel')">
          {{ t('Cancel') }}
        </AppButton>
        <AppButton type="submit" :loading="busy">{{ t('Save') }}</AppButton>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.dialog {
  width: min(26rem, calc(100vw - 2rem));
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-large, 1rem);
  background: var(--md-sys-color-surface-container-high);
  color: var(--md-sys-color-on-surface);
}

.dialog::backdrop {
  background: rgb(0 0 0 / 45%);
}

.dialog__body {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-5, 1.5rem);
}

.dialog__title {
  margin: 0;
  font-size: var(--md-sys-typescale-title-large-size, 1.35rem);
}

.dialog__label {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.dialog__field {
  width: 100%;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
  font: inherit;
}

.dialog__field:focus {
  border-color: var(--md-sys-color-primary);
  outline: none;
}

.dialog__error {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.dialog__actions {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  margin-top: var(--md-spacing-2);
}

.dialog__spacer {
  flex: 1;
}

.dialog__danger {
  color: var(--md-sys-color-error);
}
</style>
