<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import { formatDateTime } from '@/formats'
import { fieldLabel, itemTypeLabel } from '@/items/labels'
import type { ItemEnvelope } from '@/stores/library'

const { t } = useI18n()

const props = defineProps<{
  item: ItemEnvelope
  children: ItemEnvelope[]
  libraryId: number
  fileUrl: (key: string, options?: { download?: boolean }) => string
}>()

const emit = defineEmits<{ open: [item: ItemEnvelope]; close: [] }>()

/** Properties shown elsewhere in the pane, or of no interest to a reader. */
const HIDDEN = new Set([
  'key',
  'version',
  'itemType',
  'parentItem',
  'tags',
  'collections',
  'relations',
  'creators',
  'deleted',
  'note',
  'md5',
  'mtime',
  'linkMode',
])

interface Creator {
  creatorType: string
  firstName?: string
  lastName?: string
  name?: string
}

const title = computed(() => (props.item.data.title as string) || t('(untitled)'))

const creators = computed<Creator[]>(() =>
  Array.isArray(props.item.data.creators) ? (props.item.data.creators as Creator[]) : [],
)

/**
 * Fields the server stamps, as opposed to fields somebody typed.
 *
 * These three are ISO instants in UTC and are shown in the reader's own zone
 * and format. Everything else -- `date`, `accessDate` as the client wrote it --
 * is text from the item and is shown as it was entered: reformatting a
 * citation's date would be rewriting the data.
 */
const TIMESTAMPS = new Set(['dateAdded', 'dateModified'])

const fields = computed(() =>
  Object.entries(props.item.data)
    .filter(([name, value]) => !HIDDEN.has(name) && typeof value === 'string' && value !== '')
    .map(([name, value]) => ({
      name,
      label: fieldLabel(name),
      value: TIMESTAMPS.has(name) ? formatDateTime(value as string) : (value as string),
    })),
)

const tags = computed(() => props.item.data.tags ?? [])

const isAttachment = computed(
  () =>
    props.item.data.itemType === 'attachment' &&
    typeof props.item.data.linkMode === 'string' &&
    props.item.data.linkMode.startsWith('imported'),
)

const isNote = computed(() => props.item.data.itemType === 'note')

/* ---- Citation, rendered by the server in the chosen style. ---- */

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

async function cite(): Promise<void> {
  citing.value = true
  citationError.value = null
  try {
    const payload = await request<{ bib: string }>(
      `/web/libraries/${props.libraryId}/items/${props.item.key}/citation?style=${style.value}`,
    )
    bibliography.value = payload.bib
  } catch (thrown) {
    citationError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    citing.value = false
  }
}

/* A citation belongs to the item it was rendered for; showing the previous
   item's is worse than showing none. */
watch(
  () => props.item.key,
  () => {
    bibliography.value = null
    citationError.value = null
  },
)

function childTitle(child: ItemEnvelope): string {
  if (child.data.itemType === 'note') {
    const text = (child.data.note ?? '').replace(/<[^>]+>/g, ' ').trim()
    return text.slice(0, 120) || t('Note')
  }
  return (child.data.title as string) || (child.data.filename as string) || child.key
}
</script>

<template>
  <article class="detail">
    <header class="detail__header">
      <ItemTypeIcon :item-type="item.data.itemType" :size="22" />
      <div class="detail__headings">
        <h2 class="detail__title">{{ title }}</h2>
        <p class="detail__type">{{ itemTypeLabel(item.data.itemType) }}</p>
      </div>
      <button class="detail__close" type="button" :aria-label="t('Close details')" @click="emit('close')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </header>

    <div v-if="isNote" class="detail__note" v-html="item.data.note"></div>

    <dl v-if="creators.length" class="detail__fields">
      <template v-for="(creator, index) in creators" :key="index">
        <dt>{{ fieldLabel(creator.creatorType) }}</dt>
        <dd>{{ creator.name ?? `${creator.firstName ?? ''} ${creator.lastName ?? ''}`.trim() }}</dd>
      </template>
    </dl>

    <dl v-if="fields.length" class="detail__fields">
      <template v-for="field in fields" :key="field.name">
        <dt>{{ field.label }}</dt>
        <dd>
          <a
            v-if="field.name === 'url' || field.name === 'DOI'"
            :href="field.name === 'DOI' ? `https://doi.org/${field.value}` : field.value"
            target="_blank"
            rel="noopener noreferrer"
          >{{ field.value }}</a>
          <span v-else>{{ field.value }}</span>
        </dd>
      </template>
    </dl>

    <p v-if="isAttachment" class="detail__actions">
      <a class="detail__link" :href="fileUrl(item.key)" target="_blank" rel="noopener">{{ t('Open file') }}</a>
      <a class="detail__link" :href="fileUrl(item.key, { download: true })">{{ t('Download') }}</a>
    </p>

    <section v-if="tags.length" class="detail__section">
      <h3 class="detail__heading">{{ t('Tags') }}</h3>
      <ul class="detail__tags">
        <li v-for="tag in tags" :key="tag.tag" class="detail__tag">{{ tag.tag }}</li>
      </ul>
    </section>

    <section v-if="children.length" class="detail__section">
      <h3 class="detail__heading">{{ t('Attachments and notes') }}</h3>
      <ul class="detail__children">
        <li v-for="child in children" :key="child.key">
          <button class="detail__child" type="button" @click="emit('open', child)">
            <ItemTypeIcon :item-type="child.data.itemType" :size="16" />
            <span>{{ childTitle(child) }}</span>
          </button>
          <a
            v-if="child.data.itemType === 'attachment' && child.data.filename"
            class="detail__link"
            :href="fileUrl(child.key)"
            target="_blank"
            rel="noopener"
          >{{ t('open') }}</a>
        </li>
      </ul>
    </section>

    <section v-if="!isNote" class="detail__section">
      <h3 class="detail__heading">{{ t('Citation') }}</h3>
      <div class="detail__cite">
        <select v-model="style" class="detail__select" :aria-label="t('Citation style')">
          <option v-for="entry in STYLES" :key="entry.id" :value="entry.id">{{ entry.name }}</option>
        </select>
        <button class="detail__button" type="button" :disabled="citing" @click="cite">
          {{ citing ? t('Rendering…') : t('Render') }}
        </button>
      </div>
      <p v-if="citationError" class="detail__error" role="alert">{{ citationError }}</p>
      <!-- Rendered by the server's own CSL processor from this item's data. -->
      <div v-else-if="bibliography" class="detail__bib" v-html="bibliography"></div>
    </section>
  </article>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  padding: var(--md-spacing-4);
  /* Measured by the pane rather than the window: what a label and its value
     have to fit into is this column, and the column is not the screen. */
  container-type: inline-size;
}

.detail__header {
  display: flex;
  align-items: flex-start;
  gap: var(--md-spacing-3);
}

.detail__headings {
  flex: 1;
  min-width: 0;
}

.detail__close {
  display: grid;
  flex: none;
  place-items: center;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.detail__close:hover {
  background: var(--md-sys-color-surface-container-high);
}

.detail__title {
  margin: 0;
  font-size: var(--md-sys-typescale-title-medium-size, 1.05rem);
  line-height: 1.35;
}

/* Sentence case here too, for the reason given in base.css. The item type is
   a caption under the title; a section heading is a heading, so it carries the
   same hairline the sidebar's panels do. */
.detail__type {
  margin: 0.15rem 0 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.detail__heading {
  margin: 0;
  padding-bottom: 0.3rem;
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.detail__fields {
  display: grid;
  grid-template-columns: minmax(6rem, 9rem) 1fr;
  gap: 0.35rem var(--md-spacing-3);
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.detail__fields dt {
  color: var(--md-sys-color-on-surface-variant);
}

.detail__fields dd {
  margin: 0;
  overflow-wrap: anywhere;
}

/*
 * In a narrow pane the label column is a third of the width, and an abstract
 * is left reading twenty characters to the line. Below that the label goes
 * above its value instead, which costs a line and buys the whole width.
 */
@container (max-width: 26rem) {
  .detail__fields {
    grid-template-columns: 1fr;
    gap: 0.15rem;
  }

  .detail__fields dt {
    font-size: var(--md-sys-typescale-body-small-size);
  }

  .detail__fields dd:not(:last-child) {
    margin-bottom: 0.5rem;
  }
}

.detail__section {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

.detail__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.detail__tag {
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  font-size: var(--md-sys-typescale-label-small-size, 0.75rem);
}

.detail__children {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.detail__children li {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
}

.detail__child {
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
  text-align: left;
  cursor: pointer;
}

.detail__child:hover {
  background: var(--md-sys-color-surface-container-high);
}

.detail__child span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail__actions {
  display: flex;
  gap: var(--md-spacing-3);
  margin: 0;
}

.detail__link {
  color: var(--md-sys-color-primary);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.detail__note {
  padding: var(--md-spacing-3);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
  font-size: var(--md-sys-typescale-body-medium-size);
  overflow-wrap: anywhere;
}

.detail__cite {
  display: flex;
  gap: var(--md-spacing-2);
}

.detail__select,
.detail__button {
  padding: 0.3rem 0.6rem;
  /* Both are controls, so their borders take `outline`. */
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

.detail__button {
  cursor: pointer;
}

.detail__bib {
  padding: var(--md-spacing-3);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
  font-size: var(--md-sys-typescale-body-medium-size);
  overflow-wrap: anywhere;
}

.detail__error {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}
</style>
