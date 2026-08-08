<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Place } from '@/collectionplaces'
import AppButton from '@/components/AppButton.vue'
import { useModal } from '@/modal'

/**
 * Where an item should go: a collection here, or another library.
 *
 * This is the keyboard's half of drag and drop. Everything it offers can be
 * done by dragging a row of the item list onto a row of the sidebar, and a
 * control that only a pointer can reach is a control some readers do not have
 * — so the same four errands are here as a dialog: file it in a collection,
 * take it out of the one being shown, put it at the library's top level, or
 * copy it into another library.
 *
 * One list rather than two, because the reader is answering one question. The
 * collections of the library being read come first, since that is where an
 * item usually goes; the other libraries are named as copies, because that is
 * what crossing a library boundary does — the original stays where it is.
 */
const props = defineProps<{
  /** What the item is called, so the dialog says what it is about. */
  title: string
  /** The library being read, and every collection in it. */
  places: Place[]
  /** The other libraries this account may write to. */
  libraries: { id: number; label: string }[]
  /** The collection the list is showing, if it is showing one. */
  currentCollection: { key: string; name: string } | null
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  submit: [
    destination: { library: number | null; collection: string | null; takeOut: boolean },
  ]
  cancel: []
}>()

const { t } = useI18n()

/* Encoded rather than held as an object, because a `select` binds one value.
   `place:` is somewhere in this library, `library:` is a copy elsewhere. */
const destination = ref(`place:${props.currentCollection?.key ?? ''}`)
const takeOut = ref(false)

/* Only a destination in this library can take it out of a collection: a copy
   into another library leaves this one exactly as it was. */
const staying = computed(() => destination.value.startsWith('place:'))

const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const field = useTemplateRef<HTMLSelectElement>('field')

/* Escape is the browser's to handle where it has a modal of its own, and
   `useModal`'s where it has not. Either way it is a cancel. */
useModal(dialog, () => emit('cancel'))

onMounted(() => {
  field.value?.focus()
})

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('cancel')
}

function submit(): void {
  const separator = destination.value.indexOf(':')
  const kind = destination.value.slice(0, separator)
  const value = destination.value.slice(separator + 1)
  if (kind === 'library') {
    emit('submit', { library: Number(value), collection: null, takeOut: false })
    return
  }
  emit('submit', {
    library: null,
    collection: value || null,
    takeOut: takeOut.value && staying.value,
  })
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog"
    :aria-label="t('Move or copy “{name}”', { name: title })"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <form class="dialog__body" @submit.prevent="submit">
      <h2 class="dialog__title">{{ t('Move or copy') }}</h2>
      <p class="dialog__what">{{ title }}</p>

      <label class="dialog__label" for="item-destination">{{ t('Put it in') }}</label>
      <select id="item-destination" ref="field" v-model="destination" class="dialog__field">
        <option v-for="place in places" :key="place.key ?? ''" :value="`place:${place.key ?? ''}`">
          {{ '  '.repeat(place.depth) + place.label }}
        </option>
        <option v-for="entry in libraries" :key="entry.id" :value="`library:${entry.id}`">
          {{ t('Copy to {name}', { name: entry.label }) }}
        </option>
      </select>

      <!--
        Filing adds; it does not move. That is Zotero's rule and the one a drag
        follows, so the way to move something is to say so — here with a
        checkbox, in the list by holding Shift while dropping.
      -->
      <label v-if="currentCollection && staying" class="dialog__check">
        <input v-model="takeOut" type="checkbox" />
        <span>{{ t('Take it out of “{name}”', { name: currentCollection.name }) }}</span>
      </label>

      <p v-if="error" class="dialog__error" role="alert">{{ error }}</p>

      <div class="dialog__actions">
        <AppButton variant="text" :disabled="busy" @click="emit('cancel')">
          {{ t('Cancel') }}
        </AppButton>
        <AppButton type="submit" :loading="busy">{{ t('Save') }}</AppButton>
      </div>
    </form>
  </dialog>
</template>
