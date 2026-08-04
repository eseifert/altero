<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import CollectionTree from '@/components/CollectionTree.vue'
import ItemDetail from '@/components/ItemDetail.vue'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import SidebarIcon from '@/components/SidebarIcon.vue'
import { fieldLabel, loadLabels } from '@/items/labels'
import { useLibraryStore, type ItemEnvelope } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

const { t } = useI18n()

const library = useLibraryStore()
const locales = useLocaleStore()

/** Columns the list offers, named by the field each one asks the server to sort by. */
const COLUMN_FIELDS = ['title', 'creator', 'date']

/* The schema names the columns, so a heading is the word the detail pane and
   Zotero itself use for the same thing, in whatever language is in force.
   `creator` is a creator type rather than a field, which is what the column
   holds: one item's authors, editors or directors under one heading. */
const columns = computed(() =>
  COLUMN_FIELDS.map((field) => ({ field, label: fieldLabel(field) })),
)

const searchText = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined

/* The detail pane exists only when there is something in it. An empty third
   column would take a fifth of the width to say nothing, and the item list is
   what the width is for. */
const showDetail = computed(() => library.selected !== null && library.libraryId !== null)

const heading = computed(() => {
  if (library.collectionName) return library.collectionName
  if (library.scope === 'trash') return t('Trash')
  if (library.scope === 'all') return t('All items')
  return library.library?.name ?? t('Library')
})

/* The display names are per language, and the account can change its language
   while the library is open, so they follow the interface rather than the
   browser. The formatting tag is the one with a region on it, and the schema
   distinguishes `pt-BR` from `pt-PT`. */
watch(
  () => locales.formatting,
  (tag) => void loadLabels(tag),
  { immediate: true },
)

onMounted(async () => {
  try {
    await library.loadLibraries()
  } catch (thrown) {
    library.failure = thrown instanceof Error ? thrown.message : String(thrown)
  }
})

/* Typing runs a query per keystroke otherwise, and the search reaches the
   database. A short pause is enough to make it one query per phrase. */
watch(searchText, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => library.setSearch(value), 250)
})

const searchField = useTemplateRef<HTMLInputElement>('searchField')

/* Clearing is a decision, not a keystroke, so it does not wait out the pause
   the way typing does. Focus stays in the field: emptying it is usually the
   start of another search rather than the end of searching. */
function clearSearch(): void {
  clearTimeout(searchTimer)
  searchText.value = ''
  library.setSearch('')
  searchField.value?.focus()
}

function titleOf(item: ItemEnvelope): string {
  if (item.data.itemType === 'note') {
    const text = (item.data.note ?? '').replace(/<[^>]+>/g, ' ').trim()
    return text.slice(0, 120) || t('Note')
  }
  return (item.data.title as string) || t('(untitled)')
}

function sortIndicator(field: string): string {
  if (library.sort !== field) return ''
  return library.direction === 'asc' ? '↑' : '↓'
}

/* The arrow is decoration; this is what the control is called. The label goes
   in as the schema wrote it, since lowercasing a heading is right in English
   and wrong in German, where every one of these is a noun. */
function sortLabel(column: { field: string; label: string }): string {
  const name = column.label
  if (library.sort !== column.field) return t('Sort by {column}', { column: name })
  return library.direction === 'asc'
    ? t('Sort by {column}, currently ascending', { column: name })
    : t('Sort by {column}, currently descending', { column: name })
}
</script>

<template>
  <div class="library" :class="{ 'library--detail': showDetail }">
    <aside class="library__sidebar">
      <nav v-if="library.libraries.length > 1" class="library__libraries" :aria-label="t('Libraries')">
        <button
          v-for="entry in library.libraries"
          :key="entry.id"
          type="button"
          :class="['library__library', { 'library__library--current': entry.id === library.libraryId }]"
          :aria-current="entry.id === library.libraryId ? 'true' : undefined"
          @click="library.openLibrary(entry.id)"
        >
          <SidebarIcon :name="entry.type === 'user' ? 'library' : 'group'" />
          <span class="library__label">
            {{ entry.name || (entry.type === 'user' ? t('My Library') : t('Group {id}', { id: entry.ownerId })) }}
          </span>
        </button>
      </nav>

      <nav class="library__scopes" :aria-label="t('Views')">
        <button
          type="button"
          :class="['library__scope', { 'library__scope--current': !library.collectionKey && library.scope === 'top' }]"
          :aria-current="!library.collectionKey && library.scope === 'top' ? 'true' : undefined"
          @click="library.selectScope('top')"
        >
          <SidebarIcon name="library" />
          <span class="library__label">{{ t('My library') }}</span>
        </button>
        <button
          type="button"
          :class="['library__scope', { 'library__scope--current': !library.collectionKey && library.scope === 'all' }]"
          :aria-current="!library.collectionKey && library.scope === 'all' ? 'true' : undefined"
          @click="library.selectScope('all')"
        >
          <SidebarIcon name="everything" />
          <span class="library__label">{{ t('Everything') }}</span>
        </button>
        <button
          type="button"
          :class="['library__scope', { 'library__scope--current': library.scope === 'trash' }]"
          :aria-current="library.scope === 'trash' ? 'true' : undefined"
          @click="library.selectScope('trash')"
        >
          <SidebarIcon name="trash" />
          <span class="library__label">{{ t('Trash') }}</span>
        </button>
      </nav>

      <section v-if="library.collections.length" class="library__panel">
        <h2 class="library__panel-title">{{ t('Collections') }}</h2>
        <CollectionTree
          :nodes="library.collections"
          :selected="library.collectionKey"
          @select="library.selectCollection($event)"
        />
      </section>

      <section v-if="library.tags.length" class="library__panel">
        <h2 class="library__panel-title">{{ t('Tags') }}</h2>
        <ul class="library__tags">
          <li v-for="tag in library.tags" :key="tag.tag">
            <button
              type="button"
              :class="['library__tag', { 'library__tag--on': library.selectedTags.includes(tag.tag) }]"
              :aria-pressed="library.selectedTags.includes(tag.tag)"
              @click="library.toggleTag(tag.tag)"
            >
              <SidebarIcon name="tag" :size="13" />
              <span class="library__label">{{ tag.tag }}</span>
            </button>
          </li>
        </ul>
      </section>
    </aside>

    <section class="library__list">
      <header class="library__header">
        <h1 class="library__heading">{{ heading }}</h1>
        <div class="library__search">
          <svg class="library__search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
            <path d="M10.75 4.75a6 6 0 100 12 6 6 0 000-12z M15.25 15.25l4 4" />
          </svg>
          <input
            ref="searchField"
            v-model="searchText"
            class="library__search-field"
            type="search"
            :placeholder="t('Search')"
            :aria-label="t('Search this library')"
          />
          <button
            v-if="searchText"
            class="library__search-clear"
            type="button"
            :aria-label="t('Clear search')"
            @click="clearSearch"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </header>

      <p v-if="library.failure" class="library__state library__state--error" role="alert">
        {{ library.failure }}
      </p>

      <!--
        A list of buttons rather than a table of rows. The columns are how the
        items are laid out, not what they are: a `role="row"` that is a button
        promises cell-by-cell navigation that nothing here implements, and the
        header cells are sort controls rather than headers.
      -->
      <div v-else class="library__table">
        <div class="library__row library__row--head">
          <span class="library__cell library__cell--icon"></span>
          <button
            v-for="column in columns"
            :key="column.field"
            type="button"
            class="library__cell library__cell--head"
            :aria-label="sortLabel(column)"
            @click="library.sortBy(column.field)"
          >
            <span aria-hidden="true">
              {{ column.label }} {{ sortIndicator(column.field) }}
            </span>
          </button>
        </div>

        <p
          v-if="library.loading && !library.items.length"
          class="library__state"
          role="status"
        >
          {{ t('Loading…') }}
        </p>
        <p v-else-if="!library.items.length" class="library__state" role="status">
          {{ t('Nothing here yet. Point the Zotero desktop app at this server and sync.') }}
        </p>

        <ul v-else class="library__items" :aria-label="t('Items in {name}', { name: heading })">
          <li v-for="item in library.items" :key="item.key">
            <button
              type="button"
              :class="[
                'library__row',
                { 'library__row--selected': library.selected?.key === item.key },
              ]"
              :aria-pressed="library.selected?.key === item.key"
              @click="library.select(item)"
            >
              <span class="library__cell library__cell--icon">
                <ItemTypeIcon :item-type="item.data.itemType" />
              </span>
              <span class="library__cell library__cell--title">{{ titleOf(item) }}</span>
              <span class="library__cell">{{ item.meta?.creatorSummary ?? '' }}</span>
              <span class="library__cell">{{ item.meta?.parsedDate ?? '' }}</span>
            </button>
          </li>
        </ul>
      </div>

      <footer class="library__footer">
        <span>{{ t('{count} item | {count} items', library.total) }}</span>
        <button
          v-if="library.hasMore"
          class="library__more"
          type="button"
          :disabled="library.loading"
          @click="library.loadMore()"
        >
          {{ library.loading ? t('Loading…') : t('Show more') }}
        </button>
      </footer>
    </section>

    <aside v-if="showDetail && library.selected && library.libraryId !== null" class="library__detail">
      <ItemDetail
        :item="library.selected"
        :children="library.children"
        :library-id="library.libraryId"
        :file-url="library.fileUrl"
        @open="library.select($event)"
        @close="library.select(null)"
      />
    </aside>
  </div>
</template>

<style scoped>
.library {
  display: grid;
  grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr);
  gap: var(--md-spacing-4);
  align-items: start;
}

.library--detail {
  grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr) minmax(18rem, 24rem);
}

.library__sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  position: sticky;
  top: var(--md-spacing-4);
}

.library__libraries,
.library__scopes {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.library__library,
.library__scope,
.library__tag {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  min-width: 0;
  padding: 0.35rem 0.6rem;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.library__library:hover,
.library__scope:hover,
.library__tag:hover {
  background: var(--md-sys-color-surface-container-high);
}

.library__library--current,
.library__scope--current,
.library__tag--on {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.library__library {
  font-weight: 500;
}

.library__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library__panel {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

/*
 * Sentence case, as base.css says headings are here: an uppercased string is
 * read letter by letter by some screen readers, and Material 3 stopped
 * shouting labels. A hairline under the word does the separating that the caps
 * were doing.
 */
.library__panel-title {
  margin: 0;
  padding-bottom: 0.3rem;
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.library__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin: 0;
  padding: 0;
  max-height: 14rem;
  overflow-y: auto;
  list-style: none;
}

/* A tag is as long as somebody made it, and the column is narrow. Wrapping
   inside the chip keeps the whole name readable; the alternative was a
   sideways scrollbar for the sake of one long tag. */
.library__tags li {
  max-width: 100%;
}

.library__tag {
  align-items: flex-start;
  max-width: 100%;
  padding: 0.15rem 0.55rem;
  border-radius: var(--md-sys-shape-corner-medium);
  font-size: var(--md-sys-typescale-label-small-size, 0.75rem);
}

.library__tag .library__label {
  overflow: visible;
  overflow-wrap: anywhere;
  white-space: normal;
}

/* The glyph sits on the first line of a wrapped name rather than in the middle
   of the chip. */
.library__tag .sidebar-icon {
  margin-top: 0.15rem;
}

.library__list {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  min-width: 0;
}

.library__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-4);
}

.library__heading {
  margin: 0;
  font-size: var(--md-sys-typescale-title-large-size, 1.35rem);
}

.library__search {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  width: min(18rem, 50%);
  padding: 0.3rem 0.6rem;
  /* A control's own border has to be discernible: `outline`, not the divider. */
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface);
}

.library__search:focus-within {
  border-color: var(--md-sys-color-primary);
}

.library__search-icon {
  flex: none;
  color: var(--md-sys-color-on-surface-variant);
}

.library__search-field {
  flex: 1;
  min-width: 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  outline: none;
}

/* WebKit draws a cancel button of its own inside a search field; two of them
   side by side is one too many. */
.library__search-field::-webkit-search-cancel-button {
  appearance: none;
}

.library__search-clear {
  display: grid;
  flex: none;
  place-items: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-full);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.library__search-clear:hover {
  background: var(--md-sys-color-surface-container-high);
  color: var(--md-sys-color-on-surface);
}

.library__table {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  overflow: hidden;
}

.library__items {
  margin: 0;
  padding: 0;
  list-style: none;
}

.library__row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) minmax(0, 14rem) 7rem;
  align-items: center;
  gap: var(--md-spacing-3);
  width: 100%;
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border: none;
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.library__row--head {
  padding: 0;
  background: var(--md-sys-color-surface-container-low);
  cursor: default;
}

.library__row:last-child {
  border-bottom: none;
}

.library__row:hover:not(.library__row--head) {
  background: var(--md-sys-color-surface-container-low);
}

.library__row--selected,
.library__row--selected:hover {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.library__cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.library__cell--title {
  color: inherit;
}

.library__cell--icon {
  display: grid;
  place-items: center;
}

.library__cell--head {
  padding: var(--md-spacing-3) 0;
  border: none;
  background: none;
  font: inherit;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
}

.library__state {
  margin: 0;
  padding: var(--md-spacing-4);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.library__state--error {
  color: var(--md-sys-color-error);
}

.library__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-3);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.library__more {
  padding: 0.3rem 0.8rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: 999px;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.library__detail {
  position: sticky;
  top: var(--md-spacing-4);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  max-height: calc(100vh - 8rem);
  overflow-y: auto;
}

@media (max-width: 60rem) {
  .library {
    grid-template-columns: 1fr;
  }

  .library__sidebar,
  .library__detail {
    position: static;
  }

  .library__row {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .library__cell:nth-child(3),
  .library__cell:nth-child(4) {
    display: none;
  }
}
</style>
