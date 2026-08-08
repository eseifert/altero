<script setup lang="ts">
import { onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { useModal } from '@/modal'
import SidebarIcon from '@/components/SidebarIcon.vue'

/**
 * Where a new collection will go, and what it will be called.
 *
 * The desktop client lets you say where a collection is created, and the answer
 * is a place in a tree rather than a name. So the dialog leads with that place —
 * the library, then every collection down to the one this will sit in — and the
 * field comes after it. Somebody who reached this from a row deep in the
 * sidebar, or with a collection selected from an earlier session, can see what
 * "here" means before they type.
 *
 * The path is shown rather than chosen, the library included. The sidebar lists
 * one library's collections at a time, under that library, so the row the plus
 * was pressed on has already said which library and which collection -- and a
 * picker here would be a second way to say it that can disagree with the first.
 *
 * A real `<dialog>`, so the browser does the parts that are easy to do badly:
 * the top layer, the backdrop, Escape, and keeping focus inside while it is up.
 */
const props = defineProps<{
  /** The library, then each collection down to the parent. Never empty. */
  path: string[]
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{ submit: [name: string]; cancel: [] }>()

const { t } = useI18n()

const name = ref('')
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const field = useTemplateRef<HTMLInputElement>('field')

/* Escape is the browser's to handle where it has a modal of its own, and
   `useModal`'s where it has not. Either way it is a cancel. */
useModal(dialog, () => emit('cancel'))

onMounted(() => {
  /* The one thing this dialog is for is typing a name into it. */
  field.value?.focus()
})

/*
 * A click on the dialog itself is a click on its backdrop -- anything inside it
 * is a child, and reports itself as the target. Dismissing that way is what
 * people expect of a small dialog, and `<dialog>` does not do it on its own.
 */
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
    :aria-label="t('New collection')"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <form class="dialog__body" @submit.prevent="submit">
      <h2 class="dialog__title">{{ t('New collection') }}</h2>

      <div class="dialog__where">
        <span class="dialog__label">{{ t('Created in') }}</span>
        <!-- The library first, then each collection under it. The separators
             are decoration: a screen reader reading the row aloud gets the
             names in order, which is the same information without the
             punctuation being spelled out. -->
        <div class="dialog__path">
          <span v-for="(step, index) in props.path" :key="index" class="dialog__step">
            <span v-if="index > 0" class="dialog__separator" aria-hidden="true">›</span>
            <SidebarIcon :name="index === 0 ? 'library' : 'collection'" />
            <span class="dialog__step-name">{{ step }}</span>
          </span>
        </div>
      </div>

      <label class="dialog__label" for="collection-name">{{ t('Name') }}</label>
      <input
        id="collection-name"
        ref="field"
        v-model="name"
        class="dialog__field"
        type="text"
        autocomplete="off"
        :disabled="busy"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="error ? 'collection-name-error' : undefined"
      />

      <p v-if="error" id="collection-name-error" class="dialog__error" role="alert">{{ error }}</p>

      <div class="dialog__actions">
        <AppButton variant="text" :disabled="busy" @click="emit('cancel')">
          {{ t('Cancel') }}
        </AppButton>
        <AppButton type="submit" :loading="busy">{{ t('Create') }}</AppButton>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.dialog__where {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

/* A path can be longer than the dialog is wide, and a name in the middle of it
   is worth as much as the one at the end, so it wraps rather than scrolls. */
.dialog__path {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem 0.35rem;
}

.dialog__step {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
}

.dialog__separator {
  margin-right: 0.15rem;
  color: var(--md-sys-color-on-surface-variant);
}

.dialog__step-name {
  /* `word-break` first: `anywhere` is Safari 15.4, and a name that does not
     wrap at all would push the dialog wider than the phone it is on. */
  word-break: break-word;
  overflow-wrap: anywhere;
}
</style>
