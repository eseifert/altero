<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import { getItemTitle } from '@/items/titles'
import { relatedKeys, useLibraryStore } from '@/stores/library'
import type { ItemEnvelope } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

/*
 * The item pane's Related section: the items this one names in `dc:relation`.
 *
 * The desktop's related box, with a search in place of its item chooser: a
 * press on a related item opens it, and where the item can be changed, *Add
 * Related* finds another one in this library and *Remove Related* takes a link
 * off. Both write both items, as the desktop does, in one library version.
 */

const { t } = useI18n()
const library = useLibraryStore()
const locale = useLocaleStore()

const props = defineProps<{
  item: ItemEnvelope
  /** Whether this account may change this item, which the server decides. */
  editable: boolean
}>()

const emit = defineEmits<{
  open: [item: ItemEnvelope]
}>()

const related = ref<ItemEnvelope[]>([])
const failure = ref<string | null>(null)
const busy = ref(false)

function titleOf(item: ItemEnvelope): string {
  return getItemTitle(item) || item.data.filename || t(item.data.itemType === 'note' ? 'Note' : '(untitled)')
}

/** Sorted by title, as the desktop sorts them. */
const shown = computed(() =>
  [...related.value].sort((a, b) => titleOf(a).localeCompare(titleOf(b), locale.formatting)),
)

const named = computed(() => relatedKeys(props.item).join(','))

async function load(): Promise<void> {
  const item = props.item
  try {
    const found = await library.relatedOf(item)
    // The pane may have moved on to another item while this was in flight.
    if (item.key === props.item.key) related.value = found
  } catch {
    // The section keeps what it had: one list in a pane that is otherwise whole.
  }
}

watch(
  () => props.item.key,
  () => {
    related.value = []
    failure.value = null
    closeSearch()
  },
)
watch([() => props.item.key, named], load, { immediate: true })

async function write(task: () => Promise<void>): Promise<void> {
  busy.value = true
  failure.value = null
  try {
    await task()
  } catch (thrown) {
    failure.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    busy.value = false
  }
}

function remove(other: ItemEnvelope): Promise<void> {
  return write(() => library.unrelateItems(props.item.key, other.key))
}

/* ---- Finding an item to relate ---- */

const searching = ref(false)
const query = ref('')
const results = ref<ItemEnvelope[] | null>(null)
const searchBox = ref<HTMLInputElement | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchRun = 0

/** What the search offers: not this item, and not what it is already related to. */
const offered = computed(() => {
  const taken = new Set([props.item.key, ...related.value.map((entry) => entry.key)])
  return (results.value ?? []).filter((entry) => !taken.has(entry.key))
})

async function openSearch(): Promise<void> {
  searching.value = true
  failure.value = null
  await nextTick()
  searchBox.value?.focus()
}

function closeSearch(): void {
  searching.value = false
  query.value = ''
  results.value = null
  clearTimeout(searchTimer)
}

function typed(): void {
  clearTimeout(searchTimer)
  if (!query.value.trim()) {
    results.value = null
    return
  }
  searchTimer = setTimeout(search, 250)
}

async function search(): Promise<void> {
  const run = ++searchRun
  try {
    const found = await library.findItems(query.value)
    if (run === searchRun) results.value = found
  } catch (thrown) {
    if (run === searchRun) failure.value = thrown instanceof Error ? thrown.message : String(thrown)
  }
}

async function add(other: ItemEnvelope): Promise<void> {
  await write(() => library.relateItems(props.item.key, [other.key]))
  if (!failure.value) closeSearch()
}
</script>

<template>
  <section v-if="shown.length || editable" class="related">
    <div class="related__heading">
      <h3 class="related__title">{{ t('Related') }}</h3>
      <button
        v-if="editable && !searching"
        class="icon-button"
        type="button"
        :aria-label="t('Add Related')"
        :title="t('Add Related')"
        :disabled="busy"
        @click="openSearch"
      >
        <AppIcon name="plus" :size="18" />
      </button>
    </div>

    <ul v-if="shown.length" class="related__list">
      <li v-for="entry in shown" :key="entry.key" class="related__row">
        <button class="related__item" type="button" @click="emit('open', entry)">
          <ItemTypeIcon :item-type="entry.data.itemType" :size="16" />
          <span class="related__label" dir="auto">{{ titleOf(entry) }}</span>
        </button>
        <button
          v-if="editable"
          class="icon-button"
          type="button"
          :aria-label="t('Remove Related')"
          :title="t('Remove Related')"
          :disabled="busy"
          @click="remove(entry)"
        >
          <AppIcon name="minus" :size="18" />
        </button>
      </li>
    </ul>

    <div v-if="searching" class="related__search" @keydown.escape.prevent="closeSearch">
      <div class="related__field">
        <input
          ref="searchBox"
          v-model="query"
          class="related__input"
          type="search"
          dir="auto"
          :aria-label="t('Search this library')"
          :placeholder="t('Search this library')"
          @input="typed"
        />
        <button
          class="icon-button"
          type="button"
          :aria-label="t('Cancel')"
          :title="t('Cancel')"
          @click="closeSearch"
        >
          <AppIcon name="close" :size="18" />
        </button>
      </div>
      <ul v-if="offered.length" class="related__list" :aria-label="t('Add Related')">
        <li v-for="entry in offered" :key="entry.key" class="related__row">
          <button class="related__item" type="button" :disabled="busy" @click="add(entry)">
            <ItemTypeIcon :item-type="entry.data.itemType" :size="16" />
            <span class="related__label" dir="auto">{{ titleOf(entry) }}</span>
            <span v-if="entry.meta.creatorSummary" class="related__byline" dir="auto">
              {{ entry.meta.creatorSummary }}<template v-if="entry.meta.parsedDate">, {{ entry.meta.parsedDate.slice(0, 4) }}</template>
            </span>
          </button>
        </li>
      </ul>
      <p v-else-if="results" class="related__empty" role="status">{{ t('No items match this search.') }}</p>
    </div>

    <p v-if="failure" class="related__error" role="alert">{{ failure }}</p>
  </section>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.related {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

/* The pane's section heading, with the desktop's add button at its end. */
.related__heading {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
}

.related__title {
  flex: 1;
  margin: 0;
  padding-bottom: 0.3rem;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.related__heading .icon-button,
.related__row .icon-button,
.related__field .icon-button {
  width: 1.75rem;
  height: 1.75rem;
}

@media (pointer: coarse) {
  .related__heading .icon-button,
  .related__row .icon-button,
  .related__field .icon-button {
    width: 2.5rem;
    height: 2.5rem;
  }
}

.related__list {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.related__row {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
}

/* Drawn like a child in the list of attachments and notes, which is the
   other place this pane opens an item from. */
.related__item {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--md-spacing-2);
  min-width: 0;
  padding: 0.25rem 0.35rem;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.related__item:hover:not(:disabled) {
  background: var(--md-sys-state-hover-surface);
}

.related__item span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.related__label {
  flex: 0 1 auto;
}

.related__byline {
  flex: 0 10 auto;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}

.related__search {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

.related__field {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-1, 0.25rem);
}

.related__input {
  box-sizing: border-box;
  flex: 1;
  min-width: 0;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

/* The close button beside it already clears and closes; a second cross
   inside the box would be two controls drawn alike doing different things. */
.related__input::-webkit-search-cancel-button {
  appearance: none;
}

.related__input:focus {
  border-color: var(--md-sys-color-primary);
  outline: none;
}

.related__empty {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.related__error {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}
</style>
