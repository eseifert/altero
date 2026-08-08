<script setup lang="ts">
import { onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { useModal } from '@/modal'

/**
 * A new name for a tag.
 *
 * The field starts holding the name the tag has, selected: a rename is nearly
 * always a correction to what is there — a misspelling, a capital, a stray
 * space — rather than a different word, and starting from the old name saves
 * retyping it. Typing over it replaces it, which is what an empty field would
 * have done anyway.
 *
 * It says what renaming does before it is done, in Zotero's own words: the tag
 * changes in every item that carries it. That is the whole of what makes this
 * different from renaming a collection, and there is no undo.
 *
 * A real `<dialog>`, as `CollectionDialog` is, so the browser does the top
 * layer, the backdrop, Escape and the focus trap.
 */
const props = defineProps<{
  /** The tag being renamed. */
  name: string
  /** How many items carry it, so the warning can count them. */
  numItems: number
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{ submit: [name: string]; cancel: [] }>()

const { t } = useI18n()

const name = ref(props.name)
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const field = useTemplateRef<HTMLInputElement>('field')

/* Escape is the browser's to handle where it has a modal of its own, and
   `useModal`'s where it has not. Either way it is a cancel. */
useModal(dialog, () => emit('cancel'))

onMounted(() => {
  field.value?.focus()
  field.value?.select()
})

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('cancel')
}

function submit(): void {
  emit('submit', name.value.trim())
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog"
    :aria-label="t('Rename tag')"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <form class="dialog__body" @submit.prevent="submit">
      <h2 class="dialog__title">{{ t('Rename tag') }}</h2>

      <p class="dialog__note">
        {{ t('The tag will be changed in all associated items.') }}
        {{ t('{count} item carries it. | {count} items carry it.', props.numItems) }}
      </p>

      <label class="dialog__label" for="tag-name">{{ t('Name') }}</label>
      <input
        id="tag-name"
        ref="field"
        v-model="name"
        class="dialog__field"
        type="text"
        autocomplete="off"
        :disabled="busy"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="error ? 'tag-name-error' : undefined"
      />

      <p v-if="error" id="tag-name-error" class="dialog__error" role="alert">{{ error }}</p>

      <div class="dialog__actions">
        <AppButton variant="text" :disabled="busy" @click="emit('cancel')">
          {{ t('Cancel') }}
        </AppButton>
        <AppButton type="submit" :loading="busy">{{ t('Rename') }}</AppButton>
      </div>
    </form>
  </dialog>
</template>
