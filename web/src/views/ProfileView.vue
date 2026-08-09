<script setup lang="ts">
/**
 * One person's published work, on a page anybody may be reading.
 *
 * What the desktop client promises when it publishes something: "Items you add
 * to My Publications will be shown on your profile page." This is that page.
 * It is the only view in the interface that draws for a visitor who is not
 * signed in, so nothing on it assumes an account: no library, no collections,
 * no controls that write.
 *
 * A list rather than the library's three panes. A reader here is reading a
 * bibliography — what the work is, who wrote it, when, under what licence, and
 * whether the file can be had — so each entry opens in place instead of
 * filling a pane beside a tree they cannot use.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import { fieldLabel, itemTypeLabel, loadLabels } from '@/items/labels'
import { LICENSES } from '@/publications/licenses'
import { useAuthStore } from '@/stores/auth'
import type { ItemEnvelope } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'
import { useProfileStore } from '@/stores/profile'

const props = defineProps<{ username: string }>()

const { t } = useI18n()
const auth = useAuthStore()
const locale = useLocaleStore()
const store = useProfileStore()

onMounted(() => void store.load(props.username))

/* The field names are the schema's, in the reader's language, exactly as in
   the library view — and taken from `formatting` rather than from the
   account's setting, which is null for the visitor this page mostly has.
   `formatting` is what that resolves to here and now, and it carries the
   region the schema distinguishes `pt-BR` from `pt-PT` by. Watched rather
   than read once, because the names always arrive after the first render. */
watch(
  () => locale.formatting,
  (tag) => void loadLabels(tag),
  { immediate: true },
)

/* /u/ada and /u/grace are the same component with a different parameter, so
   the load has to follow the parameter rather than the mount. */
watch(
  () => props.username,
  (name) => void store.load(name),
)

/**
 * Fields worth showing under a publication, in the order they are shown.
 *
 * Not every field the item has: this is somebody else's bibliography, and the
 * ones that matter to a reader are what it is, where it appeared, and how to
 * reach it. The rest is in the citation, which the server renders in full.
 */
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

/**
 * The licence the work states, and where that licence is published.
 *
 * Matched against the table the publishing wizard writes from, so a work
 * published here links to the deed a reader can act on. A `rights` field
 * saying anything else is shown as the text it is: it is data somebody typed,
 * and guessing a URL for it would be inventing a permission.
 */
function license(item: ItemEnvelope): { name: string; url: string | null } | null {
  const rights = item.data.rights
  if (typeof rights !== 'string' || !rights) return null
  const known = LICENSES.find((entry) => entry.name === rights)
  return { name: rights, url: known?.url ?? null }
}

function attachments(): ItemEnvelope[] {
  return store.children.filter((child) => child.data.itemType === 'attachment')
}

function notes(): ItemEnvelope[] {
  return store.children.filter((child) => child.data.itemType === 'note')
}

/** What an attachment is called: its title, else its filename, else its key. */
function attachmentName(child: ItemEnvelope): string {
  return (child.data.title as string) || (child.data.filename as string) || child.key
}

/** Whether this server holds the bytes, as opposed to a bookmarked address. */
function isStored(child: ItemEnvelope): boolean {
  return typeof child.data.linkMode === 'string' && child.data.linkMode.startsWith('imported')
}

const heading = computed(() => store.profile?.displayName ?? props.username)

/* ---- Citation, rendered by the server in the chosen style. ---- */

/**
 * The same six styles the library's detail pane offers.
 *
 * A list of somebody's work is where a reader is most likely to want a citation
 * of it, and the server already renders them from this item's own data — so the
 * page asks for one rather than growing a second CSL implementation, in a
 * second language, to disagree with the first.
 */
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
      `/web/profiles/${encodeURIComponent(props.username)}/items/${key}/citation?style=${style.value}`,
    )
    bibliography.value = payload.bib
  } catch (thrown) {
    citationError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    citing.value = false
  }
}

/* A citation belongs to the entry it was rendered for; showing the previous
   one under the next work is worse than showing none. */
watch(
  () => store.opened,
  () => {
    bibliography.value = null
    citationError.value = null
  },
)

/** What the owner's own setting means, said in a sentence on their own page. */
const audience = computed(() => {
  switch (store.profile?.visibility) {
    case 'public':
      return t('Anyone can see this page, with no account here.')
    case 'users':
      return t('Only people signed in to this server can see this page.')
    case 'private':
      return t('Nobody but you can see this page.')
    default:
      return ''
  }
})
</script>

<template>
  <div class="profile">
    <p v-if="store.busy" class="profile__status">{{ t('Loading…') }}</p>

    <!--
      A profile nobody may read is reported as absent, so this one message
      covers both. The hint below it is the useful half of what the server
      will not say: some pages here are shown only to people signed in.
    -->
    <section v-else-if="store.missing" class="profile__empty">
      <h1>{{ t('No such profile') }}</h1>
      <p>{{ t('Nobody here goes by that name.') }}</p>
      <p v-if="!auth.isAuthenticated">
        {{ t('Some profiles are shown only to people signed in.') }}
        <!-- Back to this page afterwards, named rather than read off the
             current route: this page is the destination whichever way the
             visitor arrived at it. -->
        <RouterLink :to="{ name: 'sign-in', query: { next: `/u/${username}` } }">
          {{ t('Sign in') }}
        </RouterLink>
      </p>
    </section>

    <!-- A refusal is `missing` above and a stopped server is this: without it
         a failure that is neither leaves the page blank, saying nothing. -->
    <p v-else-if="!store.profile && store.error" class="profile__error" role="alert">
      {{ store.error }}
    </p>

    <template v-else-if="store.profile">
      <header class="profile__header">
        <h1 class="profile__name">{{ heading }}</h1>
        <p class="profile__handle">{{ store.profile.username }}</p>
        <p class="profile__count">
          {{
            t(
              '{count} publication | {count} publications',
              { count: store.profile.numPublications },
              store.profile.numPublications,
            )
          }}
        </p>
      </header>

      <!-- Shown to the owner and to nobody else: the server sends `visibility`
           to them alone. -->
      <p v-if="store.profile.owner" class="profile__own" role="status">
        <span>{{ t('This is your public page.') }} {{ audience }}</span>
        <RouterLink :to="{ name: 'settings', params: { section: 'profile' } }">
          {{ t('Change who can see it') }}
        </RouterLink>
      </p>

      <p v-if="store.error" class="profile__error" role="alert">{{ store.error }}</p>

      <p v-if="!store.items.length" class="profile__status">
        {{ t('Nothing has been published here yet.') }}
      </p>

      <ol v-else class="profile__list">
        <li v-for="item in store.items" :key="item.key" class="publication">
          <button
            class="publication__summary"
            type="button"
            :aria-expanded="store.opened === item.key"
            @click="store.open(props.username, item.key)"
          >
            <ItemTypeIcon :item-type="item.data.itemType" :size="18" />
            <span class="publication__headings">
              <span class="publication__title">{{ title(item) }}</span>
              <span class="publication__byline">
                <span v-if="creators(item)">{{ creators(item) }}</span>
                <span v-if="stated(item)" class="publication__date">{{ stated(item) }}</span>
                <span class="publication__type">{{ itemTypeLabel(item.data.itemType) }}</span>
              </span>
            </span>
          </button>

          <div v-if="store.opened === item.key" class="publication__detail">
            <p v-if="abstract(item)" class="publication__abstract">{{ abstract(item) }}</p>

            <dl v-if="shownFields(item).length" class="publication__fields">
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

            <!-- The answer to the wizard's licence question, linked to the
                 deed when it is one of the licences it offers. -->
            <p v-if="license(item)" class="publication__rights">
              <span class="publication__label">{{ fieldLabel('rights') }}</span>
              <a
                v-if="license(item)!.url"
                :href="license(item)!.url!"
                target="_blank"
                rel="noopener noreferrer license"
                >{{ license(item)!.name }}</a
              >
              <span v-else>{{ license(item)!.name }}</span>
            </p>

            <section v-if="attachments().length" class="publication__section">
              <!-- Zotero's own word for these, so the two applications read as
                   one vocabulary. -->
              <h2 class="publication__heading">{{ t('Attachments') }}</h2>
              <ul class="publication__files">
                <li v-for="child in attachments()" :key="child.key">
                  <template v-if="isStored(child)">
                    <a
                      :href="store.fileUrl(props.username, child.key)"
                      target="_blank"
                      rel="noopener"
                      >{{ attachmentName(child) }}</a
                    >
                    <a
                      class="publication__download"
                      :href="store.fileUrl(props.username, child.key, { download: true })"
                      >{{ t('Download') }}</a
                    >
                  </template>
                  <!-- A bookmark: the address travels with the item, the bytes
                       were never here. -->
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
            </section>

            <section class="publication__section">
              <h2 class="publication__heading">{{ t('Citation') }}</h2>
              <div class="publication__cite">
                <select v-model="style" class="publication__select" :aria-label="t('Citation style')">
                  <option v-for="entry in STYLES" :key="entry.id" :value="entry.id">
                    {{ entry.name }}
                  </option>
                </select>
                <button
                  class="publication__button"
                  type="button"
                  :disabled="citing"
                  @click="cite(item.key)"
                >
                  {{ citing ? t('Rendering…') : t('Render') }}
                </button>
              </div>
              <p v-if="citationError" class="profile__error" role="alert">{{ citationError }}</p>
              <!-- Rendered by the server's own CSL processor from this item's data. -->
              <div v-else-if="bibliography" class="publication__bib" v-html="bibliography"></div>
            </section>

            <section v-if="notes().length" class="publication__section">
              <h2 class="publication__heading">{{ t('Notes') }}</h2>
              <!-- The note as its author wrote it, which Zotero stores as
                   HTML. The same rendering the library view gives it. -->
              <div
                v-for="child in notes()"
                :key="child.key"
                class="publication__note"
                v-html="child.data.note"
              ></div>
            </section>
          </div>
        </li>
      </ol>

      <button
        v-if="store.hasMore"
        class="profile__more"
        type="button"
        :disabled="store.loadingMore"
        @click="store.more(props.username)"
      >
        {{ store.loadingMore ? t('Loading…') : t('Show more') }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.profile {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-5);
}

.profile__header {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
}

.profile__name {
  margin: 0;
}

.profile__handle,
.profile__count,
.profile__status {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.profile__own {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-3);
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.profile__error {
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

.profile__empty h1 {
  margin: 0 0 var(--md-spacing-2);
}

.profile__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
}

/* A hairline between entries rather than a card each: the page is one list,
   and boxing every row would make a bibliography look like a dashboard. */
.publication + .publication {
  border-top: 1px solid var(--md-sys-color-outline-variant);
}

.publication__summary {
  display: flex;
  align-items: flex-start;
  gap: var(--md-spacing-3);
  width: 100%;
  padding: var(--md-spacing-4) var(--md-spacing-2);
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.publication__summary:hover {
  background: var(--md-sys-state-hover-surface);
}

.publication__headings {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
  min-width: 0;
}

.publication__title {
  font-size: var(--md-sys-typescale-title-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.publication__byline {
  display: flex;
  flex-wrap: wrap;
  gap: var(--md-spacing-2);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.publication__type {
  color: var(--md-sys-color-outline);
}

.publication__detail {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding: 0 var(--md-spacing-2) var(--md-spacing-5) calc(var(--md-spacing-3) + 18px);
}

.publication__abstract {
  margin: 0;
  max-width: 60ch;
}

.publication__fields {
  display: grid;
  grid-template-columns: minmax(6rem, max-content) 1fr;
  gap: var(--md-spacing-1) var(--md-spacing-4);
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.publication__fields dt {
  color: var(--md-sys-color-on-surface-variant);
}

.publication__fields dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.publication__rights {
  display: flex;
  flex-wrap: wrap;
  gap: var(--md-spacing-2);
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.publication__label {
  color: var(--md-sys-color-on-surface-variant);
}

.publication__heading {
  margin: 0 0 var(--md-spacing-2);
  font-size: var(--md-sys-typescale-title-small-size);
  font-weight: var(--md-sys-typescale-weight-medium);
  color: var(--md-sys-color-on-surface-variant);
}

.publication__files {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.publication__download {
  margin-inline-start: var(--md-spacing-3);
}

.publication__cite {
  display: flex;
  gap: var(--md-spacing-2);
  align-items: center;
}

.publication__select,
.publication__button {
  padding: 0.3rem 0.6rem;
  /* Both are controls, so their borders take `outline`, as the detail pane's
     pair of the same two do. */
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

.publication__button {
  cursor: pointer;
}

.publication__bib {
  margin-top: var(--md-spacing-2);
  padding: var(--md-spacing-3);
  max-width: 60ch;
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
  font-size: var(--md-sys-typescale-body-medium-size);
  overflow-wrap: anywhere;
}

.publication__note {
  max-width: 60ch;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.profile__more {
  align-self: flex-start;
  padding: var(--md-spacing-2) var(--md-spacing-4);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-full);
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
</style>
