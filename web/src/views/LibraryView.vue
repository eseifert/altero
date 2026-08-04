<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import CollectionTree from '@/components/CollectionTree.vue'
import ItemDetail from '@/components/ItemDetail.vue'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import SidebarIcon from '@/components/SidebarIcon.vue'
import { loadLabels } from '@/items/labels'
import { useLibraryStore, type ItemEnvelope } from '@/stores/library'

const library = useLibraryStore()

/** Columns the list offers, with the sort field each one asks the server for. */
const COLUMNS = [
  { field: 'title', label: 'Title' },
  { field: 'creator', label: 'Creator' },
  { field: 'date', label: 'Date' },
]

const searchText = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined

/* The detail pane exists only when there is something in it. An empty third
   column would take a fifth of the width to say nothing, and the item list is
   what the width is for. */
const showDetail = computed(() => library.selected !== null && library.libraryId !== null)

const heading = computed(() => {
  if (library.collectionName) return library.collectionName
  if (library.scope === 'trash') return 'Trash'
  if (library.scope === 'all') return 'All items'
  return library.library?.name ?? 'Library'
})

onMounted(async () => {
  loadLabels(navigator.language)
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

function titleOf(item: ItemEnvelope): string {
  if (item.data.itemType === 'note') {
    const text = (item.data.note ?? '').replace(/<[^>]+>/g, ' ').trim()
    return text.slice(0, 120) || 'Note'
  }
  return (item.data.title as string) || '(untitled)'
}

function sortIndicator(field: string): string {
  if (library.sort !== field) return ''
  return library.direction === 'asc' ? '↑' : '↓'
}
</script>

<template>
  <div class="library" :class="{ 'library--detail': showDetail }">
    <aside class="library__sidebar">
      <nav v-if="library.libraries.length > 1" class="library__libraries" aria-label="Libraries">
        <button
          v-for="entry in library.libraries"
          :key="entry.id"
          type="button"
          :class="['library__library', { 'library__library--current': entry.id === library.libraryId }]"
          @click="library.openLibrary(entry.id)"
        >
          <SidebarIcon :name="entry.type === 'user' ? 'library' : 'group'" />
          <span class="library__label">
            {{ entry.name || (entry.type === 'user' ? 'My Library' : `Group ${entry.ownerId}`) }}
          </span>
        </button>
      </nav>

      <nav class="library__scopes" aria-label="Views">
        <button
          type="button"
          :class="['library__scope', { 'library__scope--current': !library.collectionKey && library.scope === 'top' }]"
          @click="library.selectScope('top')"
        >
          <SidebarIcon name="library" />
          <span class="library__label">My library</span>
        </button>
        <button
          type="button"
          :class="['library__scope', { 'library__scope--current': !library.collectionKey && library.scope === 'all' }]"
          @click="library.selectScope('all')"
        >
          <SidebarIcon name="everything" />
          <span class="library__label">Everything</span>
        </button>
        <button
          type="button"
          :class="['library__scope', { 'library__scope--current': library.scope === 'trash' }]"
          @click="library.selectScope('trash')"
        >
          <SidebarIcon name="trash" />
          <span class="library__label">Trash</span>
        </button>
      </nav>

      <section v-if="library.collections.length" class="library__panel">
        <h2 class="library__panel-title">Collections</h2>
        <CollectionTree
          :nodes="library.collections"
          :selected="library.collectionKey"
          @select="library.selectCollection($event)"
        />
      </section>

      <section v-if="library.tags.length" class="library__panel">
        <h2 class="library__panel-title">Tags</h2>
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
        <input
          v-model="searchText"
          class="library__search"
          type="search"
          placeholder="Search"
          aria-label="Search this library"
        />
      </header>

      <p v-if="library.failure" class="library__state library__state--error" role="alert">
        {{ library.failure }}
      </p>

      <div v-else class="library__table" role="table">
        <div class="library__row library__row--head" role="row">
          <span class="library__cell library__cell--icon" role="columnheader"></span>
          <button
            v-for="column in COLUMNS"
            :key="column.field"
            type="button"
            class="library__cell library__cell--head"
            role="columnheader"
            :aria-sort="
              library.sort === column.field
                ? library.direction === 'asc'
                  ? 'ascending'
                  : 'descending'
                : 'none'
            "
            @click="library.sortBy(column.field)"
          >
            {{ column.label }} <span aria-hidden="true">{{ sortIndicator(column.field) }}</span>
          </button>
        </div>

        <p v-if="library.loading && !library.items.length" class="library__state">Loading…</p>
        <p v-else-if="!library.items.length" class="library__state">
          Nothing here yet. Point the Zotero desktop app at this server and sync.
        </p>

        <button
          v-for="item in library.items"
          :key="item.key"
          type="button"
          :class="['library__row', { 'library__row--selected': library.selected?.key === item.key }]"
          role="row"
          @click="library.select(item)"
        >
          <span class="library__cell library__cell--icon" role="cell">
            <ItemTypeIcon :item-type="item.data.itemType" />
          </span>
          <span class="library__cell library__cell--title" role="cell">{{ titleOf(item) }}</span>
          <span class="library__cell" role="cell">{{ item.meta?.creatorSummary ?? '' }}</span>
          <span class="library__cell" role="cell">{{ item.meta?.parsedDate ?? '' }}</span>
        </button>
      </div>

      <footer class="library__footer">
        <span>{{ library.total }} {{ library.total === 1 ? 'item' : 'items' }}</span>
        <button
          v-if="library.hasMore"
          class="library__more"
          type="button"
          :disabled="library.loading"
          @click="library.loadMore()"
        >
          {{ library.loading ? 'Loading…' : 'Show more' }}
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

.library__panel-title {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
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
  width: min(18rem, 50%);
  padding: 0.35rem 0.7rem;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: 999px;
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

.library__table {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  overflow: hidden;
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
  border: 1px solid var(--md-sys-color-outline-variant);
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
