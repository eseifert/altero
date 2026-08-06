<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import CollectionDialog from '@/components/CollectionDialog.vue'
import CollectionTree from '@/components/CollectionTree.vue'
import ItemDetail from '@/components/ItemDetail.vue'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import SidebarIcon from '@/components/SidebarIcon.vue'
import TagDialog from '@/components/TagDialog.vue'
import { fieldLabel, loadLabels } from '@/items/labels'
import {
  useLibraryStore,
  type CollectionNode,
  type ItemEnvelope,
  type TagEntry,
} from '@/stores/library'
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

/*
 * A list can be empty for half a dozen reasons and only one of them is "this
 * server has not been synced to". Telling somebody who has just searched, or
 * opened an empty collection, to go and point Zotero at this server reads as
 * though their sync had failed, so the advice is kept for the one case it
 * answers: a library nothing has ever been put into.
 *
 * The filters come first because they are the reader's own doing and the
 * quickest thing to undo, and both are named when both are on -- clearing
 * either one alone may well leave the list just as empty.
 */
const emptyMessage = computed(() => {
  const searching = library.search.trim().length > 0
  const tagged = library.selectedTags.length > 0
  if (searching && tagged) return t('No items match this search and the selected tags.')
  if (searching) return t('No items match this search.')
  if (tagged) return t('No items carry the selected tags.')

  if (library.scope === 'trash') return t('The trash is empty.')
  if (library.collectionKey) return t('This collection is empty.')
  /* A group fills up when a member syncs into it, and that member need not be
     whoever is reading this -- nor, in a read-only group, can it be. */
  if (library.library?.type === 'group') return t('Nothing has been added to this group yet.')
  return t('Nothing here yet. Point the Zotero desktop app at this server and sync.')
})

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

/*
 * Making and removing a collection.
 *
 * One pending action at a time, held here rather than in the tree: the tree
 * recurses into itself, so state kept in it would be per level, and there is
 * only ever one of these on screen.
 *
 * Making one opens a dialog, because it takes two answers -- where, and what to
 * call it -- and the first of those is a place in a tree that the dialog has to
 * show. Removing one asks in place, as everything else here does, because it
 * takes no answer beyond yes.
 */
type Pending =
  | { kind: 'create'; parent: CollectionNode | null }
  | { kind: 'delete'; target: CollectionNode }

const pending = ref<Pending | null>(null)
const busy = ref(false)
const collectionError = ref<string | null>(null)

/* What the sidebar calls a library, so the dialog's path starts with the row
   the reader can see rather than with a second name for the same thing. */
function libraryLabel(entry: { type: string; name: string; ownerId: number }): string {
  if (entry.name) return entry.name
  return entry.type === 'user' ? t('My Library') : t('Group {id}', { id: entry.ownerId })
}

/*
 * Where the collection about to be made will go: the library, then every
 * collection down to the one it will sit inside.
 *
 * Every row that can hold collections offers the same plus, and each one acts
 * on itself -- the library's makes one at its top level, a collection's makes
 * one inside that collection. Nothing depends on what is selected, so the row
 * you press is the answer to where it goes.
 */
const creatingIn = computed(() => (pending.value?.kind === 'create' ? pending.value.parent : null))

const creatingPath = computed(() => {
  const here = library.library ? [libraryLabel(library.library)] : [t('Library')]
  const parent = creatingIn.value
  return parent ? [...here, ...library.pathTo(parent.key).map((node) => node.data.name)] : here
})

function startNew(parent: CollectionNode | null): void {
  pending.value = { kind: 'create', parent }
  collectionError.value = null
}

function startDelete(target: CollectionNode): void {
  pending.value = { kind: 'delete', target }
  collectionError.value = null
}

function cancel(): void {
  pending.value = null
  collectionError.value = null
}

/* Whatever the failure was, it is shown where the action was taken rather than
   in the item list, which is about something else entirely. */
async function run(action: () => Promise<void>): Promise<void> {
  busy.value = true
  collectionError.value = null
  try {
    await action()
    cancel()
  } catch (thrown) {
    collectionError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    busy.value = false
  }
}

async function submitCollection(name: string): Promise<void> {
  const current = pending.value
  if (current?.kind !== 'create') return

  if (!name) {
    /* Said here rather than sent to be refused: the server would say the same
       thing after a round trip. */
    collectionError.value = t('A collection needs a name.')
    return
  }
  await run(() => library.createCollection(name, current.parent?.key ?? null))
}

async function confirmDelete(): Promise<void> {
  const current = pending.value
  if (current?.kind !== 'delete') return
  await run(() => library.deleteCollection(current.target.key))
}

/*
 * Renaming a tag.
 *
 * Its own state rather than another `Pending`: this one is not about the
 * collection tree, and it survives a failure differently — the dialog stays up
 * with what was typed still in it, so a name the server refused can be
 * corrected rather than typed again.
 */
const renaming = ref<TagEntry | null>(null)
const tagBusy = ref(false)
const tagError = ref<string | null>(null)

function startRename(tag: TagEntry): void {
  renaming.value = tag
  tagError.value = null
}

function cancelRename(): void {
  renaming.value = null
  tagError.value = null
}

async function submitRename(name: string): Promise<void> {
  const current = renaming.value
  if (!current) return

  if (!name) {
    tagError.value = t('A tag needs a name.')
    return
  }

  tagBusy.value = true
  tagError.value = null
  try {
    await library.renameTag(current.tag, name)
    cancelRename()
  } catch (thrown) {
    tagError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    tagBusy.value = false
  }
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
      <!--
        The views belong to a library, so they are drawn inside the one they
        act on rather than in a list of their own above every library. Moving
        to a group takes them with it, which is the point: "Trash" under a
        group is that group's trash, and a column that showed one Trash over a
        list of libraries invited the reading that there is only the one.

        The library is named even when it is the only one. It used to be left
        out there, on the grounds that a single library needs no hierarchy and
        the row would name it twice over -- but a personal library carries the
        account's own name, so the row above "My library" reads "Ada", and it
        is the row everything under it hangs from. It is also where a
        collection is added, which needs somewhere to be.
      -->
      <nav class="library__libraries" :aria-label="t('Libraries')">
        <template v-for="entry in library.libraries" :key="entry.id">
          <div class="library__nav-row">
            <button
              type="button"
              :class="['library__library', { 'library__library--current': entry.id === library.libraryId }]"
              :aria-current="entry.id === library.libraryId ? 'true' : undefined"
              @click="library.openLibrary(entry.id)"
            >
              <SidebarIcon :name="entry.type === 'user' ? 'library' : 'group'" />
              <span class="library__label">{{ libraryLabel(entry) }}</span>
            </button>

            <!--
              The library's own plus, beside the name the collections hang
              from, and the same control a collection row carries: this row is
              the top level, so its plus makes a collection there. Only on the
              library being read -- the tree below belongs to that one, and a
              plus on another would be a write to a library nothing on screen
              is showing.
            -->
            <span
              v-if="entry.id === library.libraryId && library.writable"
              class="library__actions"
            >
              <button
                class="library__action"
                type="button"
                :aria-label="t('New collection')"
                :title="t('New collection')"
                @click="startNew(null)"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round" aria-hidden="true">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
            </span>
          </div>

          <!--
            The views and the collections are one list, because they are one
            thing: everything this library can be narrowed to. A heading over
            the collections would have said they were a separate kind of place
            to be, and they are not -- the desktop client puts them in the same
            column for the same reason. The rows share a twisty column so that
            "Trash" and a collection line up rather than sitting a step apart.
          -->
          <div
            v-if="entry.id === library.libraryId"
            class="library__scopes library__scopes--nested"
            role="group"
            :aria-label="libraryLabel(entry)"
          >
            <div class="library__scope-row">
              <span class="library__twisty" aria-hidden="true"></span>
              <button
                type="button"
                :class="['library__scope', { 'library__scope--current': !library.collectionKey && library.scope === 'top' }]"
                :aria-current="!library.collectionKey && library.scope === 'top' ? 'true' : undefined"
                @click="library.selectScope('top')"
              >
                <SidebarIcon name="library" />
                <span class="library__label">{{ t('My library') }}</span>
              </button>
            </div>
            <div class="library__scope-row">
              <span class="library__twisty" aria-hidden="true"></span>
              <button
                type="button"
                :class="['library__scope', { 'library__scope--current': !library.collectionKey && library.scope === 'all' }]"
                :aria-current="!library.collectionKey && library.scope === 'all' ? 'true' : undefined"
                @click="library.selectScope('all')"
              >
                <SidebarIcon name="everything" />
                <span class="library__label">{{ t('Everything') }}</span>
              </button>
            </div>
            <div class="library__scope-row">
              <span class="library__twisty" aria-hidden="true"></span>
              <button
                type="button"
                :class="['library__scope', { 'library__scope--current': library.scope === 'trash' }]"
                :aria-current="library.scope === 'trash' ? 'true' : undefined"
                @click="library.selectScope('trash')"
              >
                <SidebarIcon name="trash" />
                <span class="library__label">{{ t('Trash') }}</span>
              </button>
            </div>

            <CollectionTree
              v-if="library.collections.length"
              :nodes="library.collections"
              :selected="library.collectionKey"
              :editable="library.writable"
              @select="library.selectCollection($event)"
              @add="startNew($event)"
              @remove="startDelete($event)"
            />
          </div>

          <template v-if="entry.id === library.libraryId">
            <!-- Below the list rather than over it, so the tree does not move
                 down while the question is being read. -->
            <p v-if="pending?.kind === 'delete'" class="collections__confirm" role="alert">
              <span>
                {{ t('Delete “{name}”?', { name: pending.target.data.name }) }}
                {{ t('The items in it stay in the library.') }}
              </span>
              <span v-if="collectionError" class="collections__error">{{ collectionError }}</span>
              <span class="collections__actions">
                <AppButton variant="text" :disabled="busy" @click="cancel">
                  {{ t('Cancel') }}
                </AppButton>
                <AppButton :loading="busy" @click="confirmDelete">{{ t('Delete') }}</AppButton>
              </span>
            </p>

          </template>
        </template>
      </nav>

      <section v-if="library.tags.length" class="library__panel">
        <h2 class="library__panel-title">{{ t('Tags') }}</h2>
        <!--
          The pill is the list item rather than the button inside it, because a
          writable library puts two controls in it: the name, which narrows the
          list, and a pencil, which renames the tag everywhere. They share one
          outline so the pair still reads as one tag.
        -->
        <ul class="library__tags">
          <li
            v-for="tag in library.tags"
            :key="tag.tag"
            :class="['library__tag', { 'library__tag--on': library.selectedTags.includes(tag.tag) }]"
          >
            <button
              type="button"
              class="library__tag-name"
              :aria-pressed="library.selectedTags.includes(tag.tag)"
              @click="library.toggleTag(tag.tag)"
            >
              <span class="library__label">{{ tag.tag }}</span>
            </button>
            <button
              v-if="library.writable"
              class="library__tag-action"
              type="button"
              :aria-label="t('Rename “{name}”', { name: tag.tag })"
              :title="t('Rename tag')"
              @click="startRename(tag)"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M4 20h4L19 9a2.8 2.8 0 10-4-4L4 16z" />
              </svg>
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
          {{ emptyMessage }}
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

    <!-- Mounted only while it is open, so it opens focused on its field and
         starts empty every time rather than holding the last thing typed. -->
    <CollectionDialog
      v-if="pending?.kind === 'create'"
      :path="creatingPath"
      :busy="busy"
      :error="collectionError"
      @submit="submitCollection"
      @cancel="cancel"
    />

    <TagDialog
      v-if="renaming"
      :name="renaming.tag"
      :num-items="renaming.numItems"
      :busy="tagBusy"
      :error="tagError"
      @submit="submitRename"
      @cancel="cancelRename"
    />
  </div>
</template>

<style scoped>
.library {
  display: grid;
  grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr);
  gap: var(--md-spacing-4);
  align-items: start;
}

/* The list and the item get the same width. An abstract is prose, often several
   hundred words of it, and in a column narrow enough to be a sidebar it is a
   ribbon of text nobody reads. Below 60rem the whole thing stacks anyway, so
   an even split never comes at the list's expense. */
.library--detail {
  grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr) minmax(0, 1fr);
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

/*
 * One step in from the library the views and collections belong to, and no
 * more: the twisty column each of those rows carries is already most of an
 * indent, and adding a level's worth on top of it pushed the whole list into
 * the middle of a column that is only fourteen characters wide.
 *
 * The rule down the left is the thread back up to the library they act on, and
 * it is the same hairline the tag panel's heading uses.
 */
.library__scopes--nested {
  margin-left: 0.3rem;
  padding-left: 0.35rem;
  border-left: 1px solid var(--md-sys-color-outline-variant);
}

/* Every row in this column is something to click and the controls that act on
   it, and the views and collections carry a twisty column besides, so a view
   and a collection put their icon in the same place. Only a collection with
   children draws anything in that first column; the rest hold it open. */
.library__nav-row,
.library__scope-row {
  display: flex;
  align-items: center;
  gap: 0.15rem;
}

.library__scope-row {
  padding-left: 0.15rem;
}

.library__twisty {
  flex: none;
  width: 1rem;
}

.library__library,
.library__scope {
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

/* The row is the flex parent now, so the button takes what is left of it and
   matches the padding a collection's name button uses. */
.library__scope {
  flex: 1;
  padding: 0.3rem 0.4rem;
}

.library__library {
  flex: 1;
}

.library__library:hover,
.library__scope:hover {
  background: var(--md-sys-color-surface-container-high);
}

.library__library--current,
.library__scope--current {
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

/* The same hover-revealed pair the collection rows carry, so the library's
   plus and a collection's plus look and behave alike. Transparent rather than
   absent, so arriving with the pointer does not move the label. */
.library__actions {
  display: flex;
  flex: none;
  gap: 0.1rem;
  opacity: 0;
  transition: opacity 120ms ease;
}

.library__nav-row:hover .library__actions,
.library__nav-row:focus-within .library__actions {
  opacity: 1;
}

.library__action {
  display: grid;
  place-items: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.library__action:hover {
  background: var(--md-sys-color-surface-container-highest);
  color: var(--md-sys-color-on-surface);
}

/* A pointer that cannot hover cannot reveal anything, and a phone showing the
   sidebar is showing all of it. */
@media (hover: none) {
  .library__actions {
    opacity: 1;
  }
}

.collections__confirm {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
  margin: 0;
  padding: var(--md-spacing-3);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.collections__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--md-spacing-2);
}

.collections__error {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.collections__empty {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
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

/*
 * A tag is a pill, here and in the item, and the two look the same: the same
 * outline, the same corner, the same size of type. What differs is only what
 * this one can do -- these narrow the list, so one that is doing so is filled.
 *
 * The fill brings its own border colour rather than dropping the border, so
 * that picking a tag does not move the ones after it by two pixels.
 *
 * The pill is the list item, and holds the name and, where the library can be
 * written to, the pencil that renames it. A tag is as long as somebody made it
 * and the column is narrow, so it wraps inside the pill; the alternative was a
 * sideways scrollbar for the sake of one long tag.
 */
.library__tag {
  display: flex;
  align-items: center;
  gap: 0.15rem;
  max-width: 100%;
  min-width: 0;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--md-sys-color-outline);
  /* A fixed corner rather than a full one: a tag long enough to wrap should be
     a rounded rectangle, and a radius that follows the height turns it into a
     lozenge with the words rattling around in the middle. On one line it is
     round enough to read as a pill anyway. */
  border-radius: var(--md-sys-shape-corner-medium);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-label-small-size, 0.75rem);
  /* The body line height is set for paragraphs. Two lines of it inside a chip
     leave a gap the chip then has to grow to hold. */
  line-height: 1.35;
}

.library__tag:hover {
  background: var(--md-sys-color-surface-container-high);
}

.library__tag--on,
.library__tag--on:hover {
  border-color: var(--md-sys-color-secondary-container);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.library__tag-name {
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  font-size: inherit;
  line-height: inherit;
  text-align: left;
  cursor: pointer;
}

/*
 * Dimmed rather than hidden until the pointer arrives. The rows above reveal
 * their controls on hover and hold the space open meanwhile; here the space is
 * inside a pill in a wrapping list, so a pencil that appeared from nothing
 * would reflow the whole panel under the pointer.
 */
.library__tag-action {
  display: grid;
  flex: none;
  place-items: center;
  width: 1rem;
  height: 1rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  opacity: 0.45;
  transition: opacity 120ms ease;
  cursor: pointer;
}

.library__tag:hover .library__tag-action,
.library__tag-action:focus-visible {
  opacity: 1;
}

.library__tag-action:hover {
  background: var(--md-sys-color-surface-container-highest);
  color: var(--md-sys-color-on-surface);
  opacity: 1;
}

.library__tag .library__label {
  overflow: visible;
  overflow-wrap: anywhere;
  white-space: normal;
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

/* The title is what the row is for, so it is the last thing to give way: two
   shares against the creator's one, and a floor under it. Creator and date can
   be read from the item once it is open; a row whose title has been squeezed to
   two letters cannot be read at all. */
.library__row {
  display: grid;
  grid-template-columns: auto minmax(7rem, 2fr) minmax(0, 1fr) minmax(0, 7rem);
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
