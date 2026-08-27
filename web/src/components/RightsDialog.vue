<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { fieldLabel } from '@/items/labels'
import { useModal } from '@/modal'
import { LICENSES, licenseCode } from '@/publications/licenses'

/**
 * What an item's Rights field says, and how to change it.
 *
 * The desktop client has no dialog for this: Rights is an ordinary field in its
 * Info pane, typed into like any other. This interface has no field editor, and
 * it does have a way to publish a work — so the one field it must be able to
 * change is this one, because the client's My Publications wizard refuses to
 * run twice on the same item and the licence would otherwise be set once and
 * for ever.
 *
 * A picker rather than a bare text box, because the licence the wizard offers
 * is the licence somebody who published here is most likely to want, and
 * getting "Creative Commons Attribution 4.0 International License" typed
 * exactly right by hand is not a thing to ask of anybody. The free-text option
 * is still there: Rights holds "© 1974 the author" as readily as a licence, and
 * an item that came from a syncing client may say anything at all.
 */
const props = defineProps<{
  /** What the item is called, so the dialog says what it is about. */
  title: string
  /** What the field says now. */
  rights: string
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  submit: [rights: string]
  cancel: []
}>()

const { t } = useI18n()

/* Whichever licence the stored value names, or free text for anything else --
   including nothing at all, which is what an item that has never said. */
const matched = LICENSES.find((entry) => entry.name === props.rights)
const choice = ref(matched ? matched.id : 'custom')
const typed = ref(matched ? '' : props.rights)

const custom = computed(() => choice.value === 'custom')

/** What the field will say, which is what the dialog is about. */
const result = computed(() =>
  custom.value ? typed.value.trim() : (LICENSES.find((e) => e.id === choice.value)?.name ?? ''),
)

const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const field = useTemplateRef<HTMLSelectElement>('field')

useModal(dialog, () => emit('cancel'))

onMounted(() => {
  field.value?.focus()
})

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('cancel')
}

function label(id: string, name: string): string {
  const code = licenseCode(id)
  return code ? `${code} — ${name}` : name
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog dialog--wide"
    :aria-label="t('Rights for “{name}”', { name: title })"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <form class="dialog__body" @submit.prevent="emit('submit', result)">
      <!-- Named as the schema names it, in whatever language the account
           reads: the pane behind this dialog labels the same field from the
           same place, and the two must not disagree about what it is called. -->
      <h2 class="dialog__title">{{ fieldLabel('rights') }}</h2>
      <p class="dialog__what">{{ title }}</p>

      <!--
        Said plainly, because changing this line on a published work changes
        the terms other people may already have relied on. The field is not
        named again here: the heading names it as the schema does, and prose
        calling it something else would be the pane and the dialog disagreeing.
      -->
      <p class="dialog__note">
        {{ t('On a work in My Publications, this is the license its files are published under.') }}
      </p>

      <label class="dialog__label" for="item-rights">{{ t('Choose a license') }}</label>
      <select id="item-rights" ref="field" v-model="choice" class="dialog__field" :disabled="busy">
        <option v-for="entry in LICENSES" :key="entry.id" :value="entry.id">
          {{ label(entry.id, entry.name) }}
        </option>
        <option value="custom">{{ t('Something else…') }}</option>
      </select>

      <template v-if="custom">
        <label class="dialog__label" for="item-rights-text">{{ fieldLabel('rights') }}</label>
        <input
          id="item-rights-text"
          v-model="typed"
          class="dialog__field"
          type="text"
          autocomplete="off"
          :disabled="busy"
        />
        <p class="dialog__note">{{ t('Leave it empty to say nothing about rights.') }}</p>
      </template>

      <!-- What will be stored, spelt out where the choice was a code: the
           field holds the licence's full name, not its abbreviation. -->
      <p v-else class="dialog__note">{{ result }}</p>

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
