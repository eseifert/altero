<script setup lang="ts">
/**
 * One shared collection, on a page whoever holds the link may be reading.
 *
 * The other half of "share a collection, not an entire library" — the half a
 * server can answer. As sync it is impossible: a Zotero client syncs libraries,
 * and scoping below one means lying to it about what a library holds. As a page
 * it is this, and nothing on it assumes an account: no libraries, no tree of
 * somebody else's collections, no control that writes.
 *
 * Shaped like the profile page rather than like the library's three panes,
 * because a reader here is reading a list — what each work is, who wrote it,
 * and whether the file can be had — and a pane beside a tree they cannot use
 * would be furniture. The one thing this page has that a profile does not is
 * the little tree of collections *inside* the shared one, when the link carries
 * them: a shared branch is still a branch, and the reader should be able to
 * walk it.
 *
 * The token is the whole credential and it is in the address bar, which is what
 * a link means. Nothing on this page reveals who made it, who else may read it,
 * or that anything else exists in the library it came from.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import { formatDate } from '@/formats'
import { fieldLabel, itemTypeLabel, loadLabels } from '@/items/labels'
import type { ItemEnvelope } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'
import { useSharedStore } from '@/stores/shared'

const props = defineProps<{ token: string }>()

const { t } = useI18n()
const locale = useLocaleStore()
const store = useSharedStore()

onMounted(() => void store.load(props.token))

/* The field names are the schema's, in the reader's language, exactly as in
   the library view — and from `active` rather than the account's setting,
   which is null for the visitor this page mostly has. */
watch(
  () => locale.active,
  (tag) => void loadLabels(tag),
  { immediate: true },
)

watch(
  () => props.token,
  (token) => void store.load(token),
)

/** The fields worth showing under an entry, in the order they are shown. */
const SHOWN = [
  'publicationTitle',
  'bookTitle',
  'publisher',
  'university',
  'institution',
  'volume',
  'issue',
  'pages',
  'DOI',
  'ISBN',
  'url',
]

function creators(item: ItemEnvelope): string {
  const list = Array.isArray(item.data.creators) ? item.data.creators : []
  return (list as { firstName?: string; lastName?: string; name?: string }[])
    .map((one) => one.name ?? `${one.firstName ?? ''} ${one.lastName ?? ''}`.trim())
    .filter(Boolean)
    .join(', ')
}

function title(item: ItemEnvelope): string {
  return (item.data.title as string) || t('(untitled)')
}

/** The item's own date, as its author typed it: never reformatted. */
function stated(item: ItemEnvelope): string {
  return (item.data.date as string) || ''
}

function shownFields(item: ItemEnvelope): { name: string; label: string; value: string }[] {
  return SHOWN.filter((name) => typeof item.data[name] === 'string' && item.data[name] !== '').map(
    (name) => ({ name, label: fieldLabel(name), value: item.data[name] as string }),
  )
}

function abstract(item: ItemEnvelope): string {
  return (item.data.abstractNote as string) || ''
}

function attachments(): ItemEnvelope[] {
  return store.children.filter((child) => child.data.itemType === 'attachment')
}

function notes(): ItemEnvelope[] {
  return store.children.filter((child) => child.data.itemType === 'note')
}

function attachmentName(child: ItemEnvelope): string {
  return (child.data.title as string) || (child.data.filename as string) || child.key
}

/** Whether this server holds the bytes, as opposed to a bookmarked address. */
function isStored(child: ItemEnvelope): boolean {
  return typeof child.data.linkMode === 'string' && child.data.linkMode.startsWith('imported')
}

/* ---- Narrowing to one collection inside the shared one ---- */

const heading = computed(() => store.shared?.collection ?? '')

async function narrow(key: string | null): Promise<void> {
  store.inside = key
  await store.refresh(props.token)
}

/* Searching redraws from the top. Debounced by the reader pressing Enter rather
   than by a timer: a shared page has no live list to keep in step with, and a
   request per keystroke against somebody else's server is not neighbourly. */
async function submitSearch(): Promise<void> {
  await store.refresh(props.token)
}

/* ---- Citation, rendered by the server in the chosen style ---- */

const STYLES = [
  { id: 'chicago-note-bibliography', name: 'Chicago (note)' },
  { id: 'chicago-author-date', name: 'Chicago (author-date)' },
  { id: 'apa', name: 'APA' },
  { id: 'modern-language-association', name: 'MLA' },
  { id: 'ieee', name: 'IEEE' },
  { id: 'nature', name: 'Nature' },
]

const style = ref(STYLES[0].id)
const bibliography = ref<string | null>(null)
const citing = ref(false)
const citationError = ref<string | null>(null)

async function cite(key: string): Promise<void> {
  citing.value = true
  citationError.value = null
  try {
    const payload = await request<{ bib: string }>(
      `/web/shared/${encodeURIComponent(props.token)}/items/${key}/citation?style=${style.value}`,
    )
    bibliography.value = payload.bib
  } catch (thrown) {
    citationError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    citing.value = false
  }
}

/* A citation belongs to the entry it was rendered for. */
watch(
  () => store.opened,
  () => {
    bibliography.value = null
    citationError.value = null
  },
)
</script>

<template>
  <div class="shared">
    <p v-if="store.busy && !store.shared" class="shared__status">{{ t('Loading…') }}</p>

    <!--
      A link that never was, one that was revoked, one that has expired and one
      whose collection has been thrown away are the same fact from here: there
      is no such page. The server does not distinguish them, and neither does
      this.
    -->
    <section v-else-if="store.missing" class="shared__empty">
      <h1>{{ t('No such link') }}</h1>
      <p>{{ t('This link has been revoked, has expired, or never existed.') }}</p>
    </section>

    <p v-else-if="!store.shared && store.error" class="shared__error" role="alert">
      {{ store.error }}
    </p>

    <template v-else-if="store.shared">
      <header class="shared__header">
        <p class="shared__from">{{ t('Shared from {library}', { library: store.shared.library }) }}</p>
        <h1 class="shared__name">{{ heading }}</h1>
        <p class="shared__count">
          {{ t('{count} item | {count} items', { count: store.shared.numItems }, store.shared.numItems) }}
        </p>
        <p v-if="store.shared.expires" class="shared__expiry">
          {{ t('This link stops working {date}.', { date: formatDate(store.shared.expires) }) }}
        </p>
      </header>

      <form class="shared__search" @submit.prevent="submitSearch">
        <label class="shared__search-label" for="shared-search">{{ t('Search') }}</label>
        <input id="shared-search" v-model="store.search" class="shared__field" type="search" />
      </form>

      <!-- The collections inside the shared one, when the link carries them.
           Flat rather than nested: this is a way of narrowing a list, not a
           second sidebar, and the reader has no library to navigate. -->
      <nav v-if="store.collections.length" class="shared__tree" :aria-label="t('Collections')">
        <button
          class="shared__crumb"
          type="button"
          :aria-pressed="store.inside === null"
          :class="{ 'shared__crumb--on': store.inside === null }"
          @click="narrow(null)"
        >
          {{ t('Everything') }}
        </button>
        <button
          v-for="entry in store.collections"
          :key="entry.key"
          class="shared__crumb"
          type="button"
          :aria-pressed="store.inside === entry.key"
          :class="{ 'shared__crumb--on': store.inside === entry.key }"
          @click="narrow(entry.key)"
        >
          {{ entry.data.name }}
        </button>
      </nav>

      <p v-if="store.error" class="shared__error" role="alert">{{ store.error }}</p>

      <p v-if="!store.items.length" class="shared__status">{{ t('Nothing here.') }}</p>

      <ol v-else class="shared__list">
        <li v-for="item in store.items" :key="item.key" class="entry">
          <button
            class="entry__summary"
            type="button"
            :aria-expanded="store.opened === item.key"
            @click="store.open(props.token, item.key)"
          >
            <ItemTypeIcon :item-type="item.data.itemType" :size="18" />
            <span class="entry__headings">
              <span class="entry__title">{{ title(item) }}</span>
              <span class="entry__byline">
                <span v-if="creators(item)">{{ creators(item) }}</span>
                <span v-if="stated(item)" class="entry__date">{{ stated(item) }}</span>
                <span class="entry__type">{{ itemTypeLabel(item.data.itemType) }}</span>
              </span>
            </span>
          </button>

          <div v-if="store.opened === item.key" class="entry__detail">
            <p v-if="abstract(item)" class="entry__abstract">{{ abstract(item) }}</p>

            <dl v-if="shownFields(item).length" class="entry__fields">
              <template v-for="field in shownFields(item)" :key="field.name">
                <dt>{{ field.label }}</dt>
                <dd>
                  <a
                    v-if="field.name === 'url' || field.name === 'DOI'"
                    :href="field.name === 'DOI' ? `https://doi.org/${field.value}` : field.value"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ field.value }}</a
                  >
                  <span v-else>{{ field.value }}</span>
                </dd>
              </template>
            </dl>

            <!-- Listed whether or not the link carries the bytes: an item whose
                 PDF is not on offer still has one, and a page that hid it would
                 be describing a different item than the library holds. -->
            <section v-if="attachments().length" class="entry__section">
              <h2 class="entry__heading">{{ t('Attachments') }}</h2>
              <ul class="entry__files">
                <li v-for="child in attachments()" :key="child.key">
                  <template v-if="isStored(child) && store.shared.files">
                    <a :href="store.fileUrl(props.token, child.key)" target="_blank" rel="noopener">
                      {{ attachmentName(child) }}
                    </a>
                    <a
                      class="entry__download"
                      :href="store.fileUrl(props.token, child.key, { download: true })"
                      >{{ t('Download') }}</a
                    >
                  </template>
                  <a
                    v-else-if="typeof child.data.url === 'string'"
                    :href="child.data.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ attachmentName(child) }}</a
                  >
                  <span v-else>{{ attachmentName(child) }}</span>
                </li>
              </ul>
              <p v-if="!store.shared.files" class="entry__note">
                {{ t('This link does not include the files themselves.') }}
              </p>
            </section>

            <section class="entry__section">
              <h2 class="entry__heading">{{ t('Citation') }}</h2>
              <div class="entry__cite">
                <select v-model="style" class="entry__select" :aria-label="t('Citation style')">
                  <option v-for="entry in STYLES" :key="entry.id" :value="entry.id">
                    {{ entry.name }}
                  </option>
                </select>
                <button class="entry__button" type="button" :disabled="citing" @click="cite(item.key)">
                  {{ citing ? t('Rendering…') : t('Render') }}
                </button>
              </div>
              <p v-if="citationError" class="shared__error" role="alert">{{ citationError }}</p>
              <div v-else-if="bibliography" class="block entry__bib" v-html="bibliography"></div>
            </section>

            <section v-if="notes().length" class="entry__section">
              <h2 class="entry__heading">{{ t('Notes') }}</h2>
              <div
                v-for="child in notes()"
                :key="child.key"
                class="entry__note-body"
                v-html="child.data.note"
              ></div>
            </section>
          </div>
        </li>
      </ol>

      <button
        v-if="store.hasMore"
        class="shared__more"
        type="button"
        :disabled="store.loadingMore"
        @click="store.more(props.token)"
      >
        {{ store.loadingMore ? t('Loading…') : t('Show more') }}
      </button>
    </template>
  </div>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.shared {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-5);
}

.shared__header {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
}

.shared__name {
  margin: 0;
}

.shared__from,
.shared__count,
.shared__expiry,
.shared__status {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
}

.shared__error {
  margin: 0;
  color: var(--md-sys-color-error);
}

.shared__search {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
}

.shared__field {
  flex: 1 1 auto;
  min-width: 0;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
}

/* A row of pills that wraps. The shared branch is usually a handful of
   collections; a library-sized tree is not what a link hands out. */
.shared__tree {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.shared__crumb {
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: 999px;
  padding: 0.25rem 0.7rem;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}

.shared__crumb--on {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.shared__list {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
  list-style: none;
  margin: 0;
  padding: 0;
}

.entry {
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-shape-corner-medium);
  overflow: hidden;
}

.entry__summary {
  display: flex;
  align-items: flex-start;
  gap: var(--md-spacing-2);
  width: 100%;
  padding: var(--md-spacing-3);
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: start;
}

.entry__headings {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.entry__title {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.entry__byline {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  color: var(--md-sys-color-on-surface-variant);
  font-size: 0.85rem;
}

.entry__detail {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding: 0 var(--md-spacing-3) var(--md-spacing-3);
}

.entry__fields {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.25rem var(--md-spacing-3);
  margin: 0;
}

.entry__fields dt {
  color: var(--md-sys-color-on-surface-variant);
}

.entry__fields dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.entry__section {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

.entry__heading {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.entry__files {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  list-style: none;
  margin: 0;
  padding: 0;
}

.entry__download {
  margin-inline-start: var(--md-spacing-2);
  font-size: 0.85rem;
}

.entry__note,
.entry__abstract {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
}

.entry__cite {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
}

.shared__more {
  align-self: center;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-shape-corner-small);
  padding: 0.4rem 1rem;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}
</style>
