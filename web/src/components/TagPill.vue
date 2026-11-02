<script setup lang="ts">
import { nextTick, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'

const props = defineProps<{
  name: string
  automatic?: boolean
  color?: string
  selected?: boolean
  filterable?: boolean
  removable?: boolean
  rename?: (name: string) => Promise<unknown>
  /** Shown in library filters; item-detail pills do not carry a count. */
  numItems?: number
}>()
const emit = defineEmits<{ filter: []; remove: []; edit: [] }>()
const { t } = useI18n()
const id = useId()
const root = useTemplateRef<HTMLLIElement>('root')
const field = useTemplateRef<HTMLInputElement>('field')
const editing = ref(false)
const draft = ref('')
const busy = ref(false)
const failure = ref<string | null>(null)
let opening = false

async function edit(): Promise<void> {
  if (!props.rename) return
  emit('edit')
  draft.value = props.name
  failure.value = null
  opening = true
  editing.value = true
  await nextTick()
  field.value?.focus()
  field.value?.select()
  opening = false
}

async function cancel(): Promise<void> {
  if (busy.value) return
  editing.value = false
  failure.value = null
  await nextTick()
  root.value?.querySelector<HTMLButtonElement>('.tag-pill__edit')?.focus()
}

async function commit(keyboard = false): Promise<void> {
  if (!editing.value || busy.value || !props.rename) return
  const name = draft.value.trim()
  if (!name) {
    failure.value = t('A tag needs a name.')
    return
  }
  const list = root.value?.parentElement
  const listId = list?.id
  busy.value = true
  failure.value = null
  try {
    if (name !== props.name) await props.rename(name)
    editing.value = false
  } catch (thrown) {
    failure.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    busy.value = false
  }
  await nextTick()
  // A renamed pill may have been replaced or merged into another one.
  // Restore keyboard focus within the same list, without taking it back
  // from a control the person reached while the request was in flight.
  if (keyboard && (document.activeElement === document.body || document.activeElement === field.value)) {
    if (editing.value) field.value?.focus()
    else if (list?.isConnected && list.id === listId) {
      const pill = [...list.querySelectorAll<HTMLElement>('.tag-pill')]
        .find((candidate) => candidate.dataset.tagName === name)
      pill?.querySelector<HTMLButtonElement>('.tag-pill__edit')?.focus()
    }
  }
}

function leave(event: FocusEvent): void {
  if (opening) return
  if (event.relatedTarget instanceof Node && root.value?.contains(event.relatedTarget)) return
  void commit()
}
</script>

<template>
  <li
    ref="root"
    class="tag-pill"
    :class="{ 'tag-pill--selected': selected, 'tag-pill--editing': editing }"
    :style="color ? { '--tag-color': color } : undefined"
    :data-tag-name="name"
    @focusout="leave"
  >
    <span v-if="color" class="tag-pill__swatch" aria-hidden="true"></span>
    <span class="tag-pill__label">
      <component
        :is="filterable ? 'button' : 'span'"
        :id="id"
        class="tag-pill__name"
        :class="{ 'tag-pill__name--editing': editing }"
        :type="filterable ? 'button' : undefined"
        dir="auto"
        :aria-pressed="filterable ? Boolean(selected) : undefined"
        :title="automatic ? t('Automatically added tag') : undefined"
        @click="filterable && emit('filter')"
      >
        {{ name }}<span v-if="automatic" class="visually-hidden">, {{ t('Automatically added tag') }}</span>
      </component>
      <input
        v-if="editing"
        :id="`${id}-input`"
        ref="field"
        v-model="draft"
        class="tag-pill__input"
        type="text"
        dir="auto"
        autocomplete="off"
        :aria-label="t('Rename tag')"
        :aria-invalid="failure ? 'true' : undefined"
        :aria-describedby="failure ? `${id}-error` : undefined"
        :disabled="busy"
        @input="failure = null"
        @keydown.enter.prevent.stop="commit(true)"
        @keydown.esc.prevent.stop="cancel"
      />
    </span>
    <span
      v-if="numItems !== undefined"
      class="tag-pill__count"
      :aria-label="t('{count} item | {count} items', numItems)"
    >{{ numItems }}</span>
    <button
      v-if="rename"
      class="tag-pill__action"
      :class="{ 'tag-pill__edit': !editing }"
      type="button"
      :aria-label="editing ? t('Cancel') : t('Rename “{name}”', { name })"
      :title="editing ? t('Cancel') : t('Rename tag')"
      :disabled="busy"
      @pointerdown="editing && $event.preventDefault()"
      @click="editing ? cancel() : edit()"
    >
      <AppIcon :name="editing ? 'close' : 'edit'" :size="16" />
    </button>
    <button
      v-if="removable"
      class="tag-pill__action tag-pill__remove"
      :class="{ 'tag-pill__remove--editing': editing }"
      type="button"
      :aria-label="t('Remove Tag')"
      :aria-describedby="id"
      :title="t('Remove Tag')"
      :disabled="editing"
      @click="emit('remove')"
    >
      <AppIcon name="close" :size="16" />
    </button>
    <p v-if="failure" :id="`${id}-error`" class="tag-pill__error" role="alert">{{ failure }}</p>
  </li>
</template>

<style scoped>
@import '@/styles/tag-pills.css';
</style>
