<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { formatDateTime } from '@/formats'
import { fieldLabel, loadLabels, typeOutline } from '@/items/labels'
import { mergeFields, mergeValue, oldestFirst, type MergeValue } from '@/items/merging'
import { getItemTitle } from '@/items/titles'
import type { MergeSnapshot, MergeValues } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps<{
  keys: string[]
  load: (keys: string[], signal?: AbortSignal) => Promise<MergeSnapshot>
  merge: (snapshot: MergeSnapshot, master: string, fields: MergeValues) => Promise<void>
}>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const locales = useLocaleStore()
const snapshot = ref<MergeSnapshot | null>(null)
const master = ref('')
const choices = ref<Record<string, number>>({})
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const stale = ref(false)
const confirming = ref(false)
const actions = useTemplateRef<HTMLElement>('actions')
const alert = useTemplateRef<HTMLElement>('alert')
let controller: AbortController | undefined

const items = computed(() => oldestFirst(snapshot.value?.items ?? []))
const sameType = computed(() => items.value.every((item) => item.data.itemType === items.value[0]?.data.itemType))
const outline = computed(() => typeOutline(items.value[0]?.data.itemType ?? ''))
const alternatives = computed(() => sameType.value && outline.value ? mergeFields(items.value, outline.value) : [])

function chooseMaster(key: string) {
  master.value = key
  confirming.value = false
  const item = items.value.find((item) => item.key === key)!
  choices.value = Object.fromEntries(alternatives.value.map((field) => [field.name,
    field.values.findIndex((value) => JSON.stringify(value) === JSON.stringify(mergeValue(item, field.name))),
  ]))
}

async function reload() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  loading.value = true
  error.value = ''
  stale.value = false
  confirming.value = false
  snapshot.value = null
  try {
    const [review] = await Promise.all([props.load([...props.keys], current.signal), loadLabels(locales.active)])
    if (current.signal.aborted) return
    snapshot.value = review
    if (sameType.value && !outline.value) throw new Error(t('Could not load the item fields.'))
    chooseMaster(items.value[0]!.key)
  } catch (failure) {
    if (current.signal.aborted) return
    snapshot.value = null
    error.value = failure instanceof Error ? failure.message : String(failure)
    stale.value = failure instanceof ApiError && failure.status === 412
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

watch(() => [...props.keys].sort().join(','), reload, { immediate: true })
onBeforeUnmount(() => controller?.abort())

function describe(value: MergeValue): string {
  if (typeof value === 'string') return value || t('(empty)')
  return value.map((creator) => {
    const name = creator.name ?? [creator.firstName, creator.lastName].filter(Boolean).join(' ')
    return `${name} (${fieldLabel(creator.creatorType)})`
  }).join('\n') || t('(empty)')
}

async function confirmation(value: boolean) {
  confirming.value = value
  await nextTick()
  actions.value?.querySelector<HTMLButtonElement>(value ? '[data-merge-confirm]' : '[data-merge-review]')?.focus()
}

async function submit() {
  if (busy.value || stale.value || !confirming.value || !snapshot.value) return
  busy.value = true
  error.value = ''
  const fields: MergeValues = Object.fromEntries(alternatives.value.map((field) => [
    field.name, field.values[choices.value[field.name] ?? 0]!,
  ]))
  try {
    // Do not cancel a POST when this pane unmounts: it may already have committed.
    await props.merge(snapshot.value, master.value, fields)
  } catch (failure) {
    stale.value = failure instanceof ApiError && failure.status === 412
    error.value = stale.value ? t('Changed elsewhere while you were editing.')
      : failure instanceof Error ? failure.message : String(failure)
    confirming.value = false
    await nextTick()
    alert.value?.focus()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <article class="merge-pane" :aria-busy="loading || busy">
    <header class="merge-pane__header">
      <h2>{{ t('Merge Items') }}</h2>
      <button class="icon-button" :aria-label="t('Clear the selection')" :disabled="busy" @click="emit('close')">
        <AppIcon name="close" :size="22" />
      </button>
    </header>
    <p v-if="loading" role="status">{{ t('Loading…') }}</p>
    <template v-else>
      <div v-if="error" ref="alert" role="alert" tabindex="-1">
        <p>{{ error }}</p>
        <AppButton data-merge-reload variant="tonal" :disabled="busy" @click="reload">{{ t('Reload') }}</AppButton>
      </div>
      <p v-if="snapshot && !sameType">{{ t('Merged items must all be of the same item type.') }}</p>
      <template v-else-if="snapshot && outline">
        <fieldset :disabled="busy || stale" class="merge-pane__versions">
          <legend>{{ t('Choose the version of the item to use as the master item:') }}</legend>
          <label v-for="(item, index) in items" :key="item.key" class="merge-pane__option">
            <input type="radio" name="merge-master" :value="item.key" :checked="master === item.key" @change="chooseMaster(item.key)">
            <span>
              <strong>{{ t('Version {version}', { version: index + 1 }) }}</strong>
              <span dir="auto">{{ getItemTitle(item) || t('(untitled)') }}</span>
              <span v-if="item.meta.creatorSummary" dir="auto">{{ item.meta.creatorSummary }}</span>
              <small>{{ fieldLabel('dateAdded') }}: {{ formatDateTime(String(item.data.dateAdded ?? '')) }}</small>
            </span>
          </label>
        </fieldset>
        <p v-if="alternatives.length">{{ t('Select fields to keep from other versions of the item:') }}</p>
        <fieldset v-for="field in alternatives" :key="field.name" :disabled="busy || stale" class="merge-pane__field">
          <legend>{{ field.name === 'creators' ? t('Creators') : fieldLabel(field.name) }}</legend>
          <label v-for="(value, index) in field.values" :key="index" class="merge-pane__option">
            <input v-model="choices[field.name]" type="radio" :name="`merge-${field.name}`" :value="index" @change="confirming = false">
            <span dir="auto">{{ describe(value) }}</span>
          </label>
        </fieldset>
        <div v-if="!stale" ref="actions" class="merge-pane__actions">
          <template v-if="confirming">
            <p class="card__warning">{{ t('Other versions will be moved to the trash.') }}</p>
            <AppButton data-merge-confirm :loading="busy" @click="submit">{{ t('Merge Items') }}</AppButton>
            <AppButton data-merge-cancel variant="text" :disabled="busy" @click="confirmation(false)">{{ t('Cancel') }}</AppButton>
          </template>
          <AppButton v-else data-merge-review @click="confirmation(true)">{{ t('Merge Items') }}</AppButton>
        </div>
      </template>
    </template>
  </article>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.merge-pane {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  padding: var(--md-spacing-4);
}

.merge-pane__header {
  display: flex;
  align-items: flex-start;
  gap: var(--md-spacing-3);
}

.merge-pane__header h2 {
  flex: 1;
  margin: 0;
  font-size: var(--md-sys-typescale-title-medium-size);
}

.merge-pane p {
  margin: 0;
}

.merge-pane fieldset {
  min-inline-size: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.merge-pane legend {
  padding: 0;
  margin-block-end: var(--md-spacing-2);
  font-weight: 500;
}

.merge-pane__option {
  display: flex;
  align-items: flex-start;
  gap: var(--md-spacing-2);
  padding-block: var(--md-spacing-2);
  cursor: pointer;
  overflow-wrap: anywhere;
}

.merge-pane__option input {
  flex-shrink: 0;
  margin-block-start: 0.25rem;
}

.merge-pane__option span {
  min-inline-size: 0;
  white-space: pre-wrap;
}

.merge-pane__versions .merge-pane__option span > * {
  display: block;
}

.merge-pane__option small {
  color: var(--md-sys-color-on-surface-variant);
}

.merge-pane__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--md-spacing-2);
}

.merge-pane__actions p {
  flex-basis: 100%;
}
</style>
