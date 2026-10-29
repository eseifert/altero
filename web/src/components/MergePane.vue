<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import SidebarIcon from '@/components/SidebarIcon.vue'
import { formatDateTime } from '@/formats'
import { fieldLabel, loadLabels, typeOutline } from '@/items/labels'
import { mergeFields, mergeValue, oldestFirst, type MergeValue } from '@/items/merging'
import { getItemTitle } from '@/items/titles'
import type { MergeSnapshot, MergeValues } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

const props = withDefaults(defineProps<{
  keys: string[]
  selected?: string[]
  writable?: boolean
  removable?: boolean
  load: (keys: string[], signal?: AbortSignal) => Promise<MergeSnapshot>
  merge: (snapshot: MergeSnapshot, master: string, fields: MergeValues) => Promise<void>
}>(), { writable: true, removable: true })
const emit = defineEmits<{
  close: []
  selection: [keys: string[]]
  master: [key: string]
  inspect: [key: string]
  move: []
  trash: []
  export: []
}>()
const { t } = useI18n()
const locales = useLocaleStore()
const id = useId()
const snapshot = ref<MergeSnapshot | null>(null)
const master = ref('')
const choices = ref<Record<string, number>>({})
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const stale = ref(false)
const confirming = ref(false)
const adjusting = ref(false)
const inspecting = ref(false)
const actions = useTemplateRef<HTMLElement>('actions')
const alert = useTemplateRef<HTMLElement>('alert')
let controller: AbortController | undefined

const items = computed(() => oldestFirst(snapshot.value?.items ?? []))
const included = computed(() => new Set(props.selected ?? props.keys))
const selectedItems = computed(() => items.value.filter((item) => included.value.has(item.key)))
const sameType = computed(() => selectedItems.value.every((item) => item.data.itemType === selectedItems.value[0]?.data.itemType))
const outline = computed(() => typeOutline(selectedItems.value[0]?.data.itemType ?? ''))
const alternatives = computed(() => sameType.value && outline.value ? mergeFields(selectedItems.value, outline.value) : [])
const canMerge = computed(() => selectedItems.value.length > 1 && sameType.value && Boolean(outline.value) && props.writable && props.removable)

function chooseMaster(key: string) {
  master.value = key
  confirming.value = false
  const item = selectedItems.value.find((item) => item.key === key)
  if (!item) return
  choices.value = Object.fromEntries(alternatives.value.map((field) => [field.name,
    field.values.findIndex((value) => JSON.stringify(value) === JSON.stringify(mergeValue(item, field.name))),
  ]))
  emit('master', key)
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
    chooseMaster(selectedItems.value[0]?.key ?? '')
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
watch(() => [...included.value].sort().join(','), () => {
  if (!snapshot.value) return
  chooseMaster(included.value.has(master.value) ? master.value : selectedItems.value[0]?.key ?? '')
})
onBeforeUnmount(() => controller?.abort())

function toggleItem(key: string) {
  const keys = new Set(included.value)
  if (!keys.delete(key)) keys.add(key)
  emit('selection', items.value.filter((item) => keys.has(item.key)).map((item) => item.key))
}

function describe(value: MergeValue | undefined): string {
  if (typeof value === 'string') return value || t('(empty)')
  return value?.map((creator) => {
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
  if (busy.value || stale.value || !confirming.value || !snapshot.value || !canMerge.value) return
  busy.value = true
  error.value = ''
  const fields: MergeValues = Object.fromEntries(alternatives.value.map((field) => [
    field.name, field.values[choices.value[field.name] ?? 0]!,
  ]))
  try {
    // Keep the original review watermark even when only a subset is merged.
    await props.merge({ ...snapshot.value, items: snapshot.value.items.filter((item) => included.value.has(item.key)) }, master.value, fields)
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
    <div class="toolbar merge-pane__tools" :aria-label="t('Items')" role="group">
      <button class="icon-button" :aria-label="t('Edit')" :title="t('Edit')" :disabled="busy || !snapshot" :aria-expanded="inspecting" :aria-controls="`${id}-inspect`" @click="inspecting = !inspecting">
        <AppIcon name="edit" :size="20" />
      </button>
      <button class="icon-button" :aria-label="adjusting ? t('Done selecting') : t('Select')" :title="t('Select')" :disabled="busy || stale || !snapshot" :aria-pressed="adjusting" @click="adjusting = !adjusting">
        <SidebarIcon name="select" :size="20" />
      </button>
      <button v-if="writable" class="icon-button" :aria-label="t('Move or copy…')" :title="t('Move or copy…')" :disabled="busy" @click="emit('move')">
        <SidebarIcon name="move" :size="20" />
      </button>
      <button v-if="removable && writable" class="icon-button" :aria-label="t('Move to trash')" :title="t('Move to trash')" :disabled="busy" @click="emit('trash')">
        <SidebarIcon name="trash" :size="20" />
      </button>
      <button class="icon-button" :aria-label="t('Export…')" :title="t('Export…')" :disabled="busy" @click="emit('export')">
        <SidebarIcon name="export" :size="20" />
      </button>
      <button v-if="!error" class="icon-button" :aria-label="t('Reload')" :title="t('Reload')" :disabled="busy || loading" @click="reload">
        <AppIcon name="redo" :size="20" />
      </button>
    </div>
    <div v-if="inspecting && snapshot" :id="`${id}-inspect`" class="merge-pane__inspect block" role="group" :aria-label="t('Edit')">
      <button v-for="item in items" :key="item.key" type="button" :data-merge-inspect="item.key" @click="emit('inspect', item.key)">
        <span dir="auto">{{ getItemTitle(item) || t('(untitled)') }}</span>
        <AppIcon name="open" :size="18" />
      </button>
    </div>
    <p v-if="loading" role="status">{{ t('Loading…') }}</p>
    <template v-else>
      <div v-if="error" ref="alert" role="alert" tabindex="-1">
        <p>{{ error }}</p>
        <AppButton data-merge-reload variant="tonal" :disabled="busy" @click="reload">{{ t('Reload') }}</AppButton>
      </div>
      <fieldset v-if="adjusting && snapshot" :disabled="busy || stale" class="merge-pane__members">
        <legend>{{ t('Select') }}</legend>
        <label v-for="item in items" :key="item.key">
          <input type="checkbox" :value="item.key" :checked="included.has(item.key)" :aria-label="t('Select “{name}”', { name: getItemTitle(item) || t('(untitled)') })" @change="toggleItem(item.key)">
          <span dir="auto">{{ getItemTitle(item) || t('(untitled)') }}</span>
        </label>
      </fieldset>
      <template v-if="snapshot && selectedItems.length">
        <label class="merge-pane__master" :for="`${id}-master`">
          {{ t('Choose the version of the item to use as the master item:') }}
        </label>
        <select :id="`${id}-master`" name="merge-master" :value="master" :disabled="busy || stale" @change="chooseMaster(($event.target as HTMLSelectElement).value)">
          <option v-for="(item, index) in selectedItems" :key="item.key" :value="item.key">
            {{ formatDateTime(String(item.data.dateAdded ?? '')) || t('Version {version}', { version: index + 1 }) }} — {{ getItemTitle(item) || t('(untitled)') }}
          </option>
        </select>
        <p v-if="!sameType">{{ t('Merged items must all be of the same item type.') }}</p>
        <p v-if="alternatives.length" class="merge-pane__instruction">{{ t('Select fields to keep from other versions of the item:') }}</p>
        <div v-for="field in alternatives" :key="field.name" class="merge-pane__field">
          <label :for="`${id}-${field.name}`">{{ field.name === 'creators' ? t('Creators') : fieldLabel(field.name) }}</label>
          <select :id="`${id}-${field.name}`" v-model="choices[field.name]" :name="`merge-${field.name}`" :disabled="busy || stale" :title="describe(field.values[choices[field.name] ?? 0])" @change="confirming = false">
            <option v-for="(value, index) in field.values" :key="index" :value="index">{{ describe(value) }}</option>
          </select>
          <details v-if="describe(field.values[choices[field.name] ?? 0]).length > 160">
            <summary>{{ t('Show more') }}</summary>
            <p dir="auto">{{ describe(field.values[choices[field.name] ?? 0]) }}</p>
          </details>
        </div>
        <div v-if="!stale" ref="actions" class="merge-pane__actions">
          <template v-if="confirming">
            <p class="card__warning">{{ t('Other versions will be moved to the trash.') }}</p>
            <AppButton data-merge-confirm :loading="busy" @click="submit">{{ t('Merge Items') }}</AppButton>
            <AppButton data-merge-cancel variant="text" :disabled="busy" @click="confirmation(false)">{{ t('Cancel') }}</AppButton>
          </template>
          <AppButton v-else data-merge-review :disabled="!canMerge" @click="confirmation(true)">{{ t('Merge Items') }}</AppButton>
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
  gap: var(--md-spacing-2);
  padding: var(--md-spacing-3);
}

.merge-pane__header, .merge-pane__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--md-spacing-2);
}

.merge-pane__header h2 {
  flex: 1;
  margin: 0;
  font-size: var(--md-sys-typescale-title-medium-size);
}

.merge-pane p {
  margin: 0;
}

.merge-pane__tools {
  align-self: flex-start;
  flex-wrap: wrap;
}

.merge-pane fieldset {
  min-inline-size: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.merge-pane legend {
  padding: 0;
  font-weight: 500;
}

.merge-pane__members label {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  min-block-size: 32px;
  cursor: pointer;
}

.merge-pane__members span {
  overflow-wrap: anywhere;
}

.merge-pane__members input {
  flex-shrink: 0;
  inline-size: 24px;
  block-size: 24px;
  accent-color: var(--md-sys-color-primary);
}

.merge-pane__master, .merge-pane__instruction {
  font-size: var(--md-sys-typescale-body-small-size);
}

.merge-pane__field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  gap: var(--md-spacing-2);
  align-items: center;
}

.merge-pane__field > label {
  overflow-wrap: anywhere;
  font-size: var(--md-sys-typescale-body-small-size);
}

.merge-pane__field details {
  grid-column: 1 / -1;
  font-size: var(--md-sys-typescale-body-small-size);
}

.merge-pane__field summary {
  min-block-size: 24px;
  cursor: pointer;
}

.merge-pane__field details p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.merge-pane select {
  min-inline-size: 0;
  inline-size: 100%;
  min-block-size: 32px;
  padding: var(--md-spacing-1);
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-extra-small);
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.merge-pane__inspect button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-2);
  inline-size: 100%;
  min-block-size: 32px;
  padding: var(--md-spacing-1);
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.merge-pane__inspect span {
  overflow-wrap: anywhere;
}

.merge-pane__actions {
  margin-block-start: var(--md-spacing-2);
}

.merge-pane__actions p {
  flex-basis: 100%;
}


@media (pointer: coarse) {
  .merge-pane select, .merge-pane .icon-button, .merge-pane__inspect button, .merge-pane__members label, .merge-pane__field summary {
    min-block-size: 44px;
  }

  .merge-pane .icon-button {
    min-inline-size: 44px;
  }

}
</style>
