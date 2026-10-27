<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { cleanLink } from '@/items/attachments'
import { useModal } from '@/modal'

/**
 * The desktop's *Attach Web Link…*: an address and, if wanted, a title.
 *
 * The address is cleaned the desktop's way before anything is sent (see
 * `cleanLink`), so a host typed without `https://` becomes a link and a word
 * that is no address is said to be one here rather than refused by the
 * server. With no title the server names the link after its address, as
 * the desktop does.
 */
defineProps<{ busy?: boolean; error?: string | null }>()

const emit = defineEmits<{ submit: [link: { url: string; title: string }]; cancel: [] }>()

const { t } = useI18n()

const address = ref('')
const title = ref('')
const refusal = ref<string | null>(null)
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const field = useTemplateRef<HTMLInputElement>('field')

useModal(dialog, () => emit('cancel'))
onMounted(() => field.value?.focus())

const REASONS = computed(() => ({
  unrecognized: t('This is not an address. Check it and try again.'),
  file: t('A file on your computer cannot be linked from the browser.'),
  scheme: t('This kind of address cannot be attached.'),
}))

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('cancel')
}

function submit(): void {
  const cleaned = cleanLink(address.value)
  if (!cleaned.ok) {
    refusal.value = REASONS.value[cleaned.reason]
    field.value?.select()
    return
  }
  refusal.value = null
  emit('submit', { url: cleaned.url, title: title.value.trim() })
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog"
    :aria-label="t('Attach Web Link')"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <form class="dialog__body" novalidate @submit.prevent="submit">
      <h2 class="dialog__title">{{ t('Attach Web Link') }}</h2>

      <label class="dialog__label" for="web-link-address">{{ t('Link') }}</label>
      <input
        id="web-link-address"
        ref="field"
        v-model="address"
        class="dialog__field"
        type="url"
        inputmode="url"
        autocomplete="url"
        dir="auto"
        :disabled="busy"
        :aria-invalid="refusal || error ? 'true' : undefined"
        :aria-describedby="refusal || error ? 'web-link-error' : undefined"
      />

      <label class="dialog__label" for="web-link-title">{{ t('Title') }}</label>
      <input
        id="web-link-title"
        v-model="title"
        class="dialog__field"
        type="text"
        autocomplete="off"
        dir="auto"
        :disabled="busy"
      />

      <p v-if="refusal || error" id="web-link-error" class="dialog__error" role="alert">
        {{ refusal || error }}
      </p>

      <div class="dialog__actions">
        <AppButton variant="text" :disabled="busy" @click="emit('cancel')">{{ t('Cancel') }}</AppButton>
        <AppButton type="submit" :loading="busy">{{ t('Attach') }}</AppButton>
      </div>
    </form>
  </dialog>
</template>
