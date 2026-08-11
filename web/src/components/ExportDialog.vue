<script setup lang="ts">
import { onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { EXPORT_FORMATS, rememberFormat, rememberedFormat } from '@/exportformats'
import { useModal } from '@/modal'

/**
 * What to write out, and in which format — `exportOptions.xhtml`, narrowed.
 *
 * The client's dialog asks three things: the format, the options that format
 * declares, and where to put the file. Only the first is a question here. The
 * options are all things a translator supports and altero's four formats do
 * not — exporting the attached files, exporting notes as their own entries,
 * abbreviating journal titles — and where the file goes is the browser's
 * business, not this application's.
 *
 * What it asks *instead* is which items, where the client has three separate
 * menu items for that. Rows picked out come first and are the answer unless
 * somebody says otherwise, because a selection is a decision somebody has just
 * made; the view and the library follow it, so that "actually, all of it" is
 * one radio button rather than a trip back to clear the selection.
 *
 * The Export control is a link rather than a button because that is what makes
 * the browser stream the file to disk and name it from the response, instead of
 * this page holding somebody's whole library in memory to hand it back to them.
 */
export interface ExportScope {
  id: string
  /** What this covers, in words: "3 items selected", "Whales", "My Library". */
  label: string
}

const props = defineProps<{
  /** What may be exported, widest last. The first is the answer offered. */
  scopes: ExportScope[]
  /** Where the file for a given scope and format comes from. */
  link: (format: string, scope: string) => string
}>()

const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()

const format = ref(rememberedFormat())
const scope = ref(props.scopes[0]?.id ?? '')

const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const field = useTemplateRef<HTMLSelectElement>('field')

useModal(dialog, () => emit('close'))

/* On the format, which is the question a reader came here to answer: the items
   are already decided, and the first choice is the one they just made. */
onMounted(() => {
  field.value?.focus()
})

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('close')
}

/* The download has already been started by the browser when this runs: the
   click on the link is not intercepted, only noticed. */
function start(): void {
  rememberFormat(format.value)
  emit('close')
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog"
    :aria-label="t('Export…')"
    @cancel.prevent="emit('close')"
    @click="backdrop"
  >
    <div class="dialog__body">
      <h2 class="dialog__title">{{ t('Export…') }}</h2>

      <!-- One thing to export and there is nothing to ask: it is named instead,
           so the dialog still says what it is about. -->
      <p v-if="scopes.length < 2" class="dialog__what">{{ scopes[0]?.label }}</p>
      <fieldset v-else class="dialog__choices">
        <legend class="dialog__label">{{ t('What to export') }}</legend>
        <label v-for="entry in scopes" :key="entry.id" class="dialog__check">
          <input v-model="scope" type="radio" name="export-scope" :value="entry.id" />
          <span>{{ entry.label }}</span>
        </label>
      </fieldset>

      <label class="dialog__label" for="export-format">{{ t('Format:') }}</label>
      <select id="export-format" ref="field" v-model="format" class="dialog__field">
        <option v-for="entry in EXPORT_FORMATS" :key="entry.id" :value="entry.id">
          {{ entry.label }}
        </option>
      </select>

      <div class="dialog__actions">
        <AppButton variant="text" @click="emit('close')">{{ t('Cancel') }}</AppButton>
        <a class="dialog__download" :href="link(format, scope)" download @click="start">
          {{ t('Export') }}
        </a>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
/* A fieldset carries the group's name for a screen reader; everything else
   about its own box gets in the way of the dialog's layout. */
.dialog__choices {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
  margin: 0;
  padding: 0;
  border: none;
}

/* A link that acts as this dialog's finishing button, and so is drawn as one.
   The filled button's shape rather than its component: `AppButton` renders a
   `<button>`, and a button cannot be the thing that fetches a file. */
.dialog__download {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 var(--md-spacing-5);
  border-radius: var(--md-sys-shape-corner-full);
  background: var(--md-sys-color-primary);
  color: var(--md-sys-color-on-primary);
  font-size: var(--md-sys-typescale-label-large-size);
  text-decoration: none;
}

.dialog__download:hover {
  filter: brightness(1.08);
}

@media (pointer: coarse) {
  .dialog__download {
    min-height: 2.75rem;
  }
}
</style>
