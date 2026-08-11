<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import SidebarIcon from '@/components/SidebarIcon.vue'
import { exportable } from '@/exportformats'
import { formatDateTime } from '@/formats'
import { fieldLabel, itemTypeLabel } from '@/items/labels'
import type { ItemEnvelope } from '@/stores/library'

const { t } = useI18n()

const props = defineProps<{
  item: ItemEnvelope
  children: ItemEnvelope[]
  libraryId: number
  fileUrl: (key: string, options?: { download?: boolean }) => string
  /** Whether this account may change the library, which the server decides. */
  writable?: boolean
  /** Whether this library has a My Publications at all: a personal one does,
   *  a group does not, and publishing is refused there. */
  publishable?: boolean
  /** Whether the list behind this pane is the My Publications view. The
   *  desktop client shows a child item's publishing button only there, and so
   *  does this: elsewhere a note's place in the list is its parent's business. */
  inPublicationsView?: boolean
}>()

/*
 * What can be done to the item, said in words.
 *
 * The item list does all of this by dragging, which is quick and which some
 * readers cannot do at all. These are the same errands as buttons, on the pane
 * that is already about this one item -- so nothing here is reachable only
 * with a pointer, and nothing needs a menu that appears under one.
 */
const emit = defineEmits<{
  open: [item: ItemEnvelope]
  close: []
  move: []
  trash: []
  restore: []
  remove: []
  publish: []
  unpublish: []
  rights: []
  export: []
}>()

/**
 * Item types with no ``rights`` field, which is the whole of that list.
 *
 * Every other type in the schema has one. Checked against
 * ``itemschema`` rather than guessed: the server refuses the write anyway, but
 * offering a control that can only be refused is a promise not to make.
 */
const WITHOUT_RIGHTS = new Set(['note', 'attachment', 'annotation'])

/** Whether this item has a bibliography entry to write out. A note has none,
 *  and altero has no note translator to make one — see `exportformats.ts`. */
const offersExport = computed(() => exportable(props.item.data.itemType))

/** Whether the item is in the trash, which decides what can be done to it. */
const trashed = computed(() => Boolean(props.item.data.deleted))

const published = computed(() => Boolean(props.item.data.inPublications))

/** Whether this item is a note or an attachment hanging off another item. */
const child = computed(() => Boolean(props.item.data.parentItem))

/**
 * Whether the pane offers to move, trash or restore this item.
 *
 * A child item is filed by its parent and trashed with it: an attachment does
 * not belong in a collection of its own, and Zotero does not offer it either.
 */
const showsTools = computed(() => Boolean(props.writable) && !child.value)

/** Whether this pane offers to change the item's Rights field. */
const editableRights = computed(
  () => Boolean(props.writable) && !WITHOUT_RIGHTS.has(props.item.data.itemType),
)

const statesRights = computed(() => Boolean(props.item.data.rights))

/**
 * Whether the pane offers to publish this item.
 *
 * A work, in a library that has a My Publications, that is not in the trash —
 * publishing something on its way out is a contradiction, and Zotero's own
 * view hides trashed items. A *child* is offered it only in the My
 * Publications view, which is where the client offers it: that is the one
 * place where a note being published or not is visible on its own.
 */
const offersPublishing = computed(
  () =>
    Boolean(props.writable) &&
    Boolean(props.publishable) &&
    !trashed.value &&
    (!child.value || Boolean(props.inPublicationsView)),
)

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

    <!--
      What can be done to this item. Filing and trashing are the top-level
      item's alone — see `showsTools` — and publishing has a rule of its own, so
      the row appears when any of them has something to offer. Exporting is the
      one that is not a write, and so is offered on its own in a library this
      account may only read.

      Glyphs, like the tools over the item list, and each carries the same words
      twice: as `aria-label`, which is what a screen reader announces, and as
      `title`, which is what a pointer reveals. Publishing draws a plus and
      unpublishing a minus, because a control that toggles has to show which way
      it is about to go — the label alone would be a sentence nobody sees until
      after they have pressed it.
    -->
    <div v-if="showsTools || offersPublishing || offersExport" class="detail__tools">
      <button
        v-if="showsTools"
        class="detail__tool"
        type="button"
        :aria-label="t('Move or copy…')"
        :title="t('Move or copy…')"
        @click="emit('move')"
      >
        <SidebarIcon name="move" :size="18" />
      </button>

      <!--
        The same errands the sidebar's My Publications row takes by drag, for
        readers who do not drag. Adding says "…" because it asks: what goes
        with the work, and under what licence. Removing does not ask here — the
        list does, above the rows, where the item can still be seen.
      -->
      <template v-if="offersPublishing">
        <button
          v-if="!published"
          class="detail__tool"
          type="button"
          :aria-label="child ? t('Show in My Publications') : t('Add to My Publications…')"
          :title="child ? t('Show in My Publications') : t('Add to My Publications…')"
          @click="emit('publish')"
        >
          <SidebarIcon name="publish" :size="18" />
        </button>
        <button
          v-else
          class="detail__tool"
          type="button"
          :aria-label="child ? t('Hide from My Publications') : t('Remove from My Publications')"
          :title="child ? t('Hide from My Publications') : t('Remove from My Publications')"
          @click="emit('unpublish')"
        >
          <SidebarIcon name="unpublish" :size="18" />
        </button>
      </template>

      <!-- Writing this item out as a file. Not behind `showsTools`: exporting
           is a read, so it is offered on a child item and in a library this
           account may only read. -->
      <button
        v-if="offersExport"
        class="detail__tool"
        type="button"
        :aria-label="t('Export…')"
        :title="t('Export…')"
        @click="emit('export')"
      >
        <SidebarIcon name="export" :size="18" />
      </button>

      <template v-if="showsTools">
        <button
          v-if="!trashed"
          class="detail__tool"
          type="button"
          :aria-label="t('Move to trash')"
          :title="t('Move to trash')"
          @click="emit('trash')"
        >
          <SidebarIcon name="trash" :size="18" />
        </button>
        <template v-else>
          <!-- Zotero's own words for this, and a key of its own: "Restore"
               alone is also what the settings page calls putting an archive
               back, and one message for the two had German telling somebody
               their item was about to be replayed from a backup. -->
          <button
            class="detail__tool"
            type="button"
            :aria-label="t('Restore to Library')"
            :title="t('Restore to Library')"
            @click="emit('restore')"
          >
            <SidebarIcon name="restore" :size="18" />
          </button>
          <!-- A bin with a cross through it rather than the bin: this is the
               one thing here that cannot be undone, and it must not look like
               the errand that can. -->
          <button
            class="detail__tool detail__tool--danger"
            type="button"
            :aria-label="t('Delete')"
            :title="t('Delete')"
            @click="emit('remove')"
          >
            <SidebarIcon name="deleteforever" :size="18" />
          </button>
        </template>
      </template>
    </div>

    <div v-if="isNote" class="card__inset detail__note" v-html="item.data.note"></div>

    <dl v-if="creators.length" class="detail__fields">
      <template v-for="(creator, index) in creators" :key="index">
        <dt>{{ fieldLabel(creator.creatorType) }}</dt>
        <dd>{{ creator.name ?? `${creator.firstName ?? ''} ${creator.lastName ?? ''}`.trim() }}</dd>
      </template>
    </dl>

    <dl v-if="fields.length || editableRights" class="detail__fields">
      <template v-for="field in fields" :key="field.name">
        <dt>{{ field.label }}</dt>
        <dd>
          <a
            v-if="field.name === 'url' || field.name === 'DOI'"
            :href="field.name === 'DOI' ? `https://doi.org/${field.value}` : field.value"
            target="_blank"
            rel="noopener noreferrer"
          >{{ field.value }}</a>
          <!--
            The one field this pane can change, and the pencil is here rather
            than beside every field because it is the only one: publishing a
            work sets its licence, and the licence has to be revisable by
            whoever set it. Everything else is still the desktop's to edit.
          -->
          <template v-else-if="field.name === 'rights' && editableRights">
            <span>{{ field.value }}</span>
            <button
              class="detail__edit"
              type="button"
              :aria-label="t('Change the rights')"
              :title="t('Change the rights')"
              @click="emit('rights')"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M4 20h4L19 9a2.8 2.8 0 10-4-4L4 16z" />
              </svg>
            </button>
          </template>
          <span v-else>{{ field.value }}</span>
        </dd>
      </template>

      <!-- An item that says nothing about rights has no row above to hang the
           pencil on, and "nothing" is exactly the state somebody publishing a
           work wants to change. -->
      <template v-if="editableRights && !statesRights">
        <dt>{{ fieldLabel('rights') }}</dt>
        <dd>
          <button class="detail__add" type="button" @click="emit('rights')">
            {{ t('Not stated — say what it is') }}
          </button>
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
      <div v-else-if="bibliography" class="card__inset detail__bib" v-html="bibliography"></div>
    </section>
  </article>
</template>

<style scoped>
@import '@/styles/surfaces.css';

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
  background: var(--md-sys-state-hover-surface);
}

@media (pointer: coarse) {
  .detail__close {
    width: 2.5rem;
    height: 2.5rem;
  }

  .detail__tool {
    width: 2.5rem;
    height: 2.5rem;
  }
}

/* A row of glyphs, drawn like the tools over the item list, because they are
   the same errands reaching the same items -- one row picked out here, several
   picked out there. Each says what it is in `aria-label` and in `title`. */
.detail__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--md-spacing-1);
}

.detail__tool {
  display: grid;
  flex: none;
  place-items: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-full);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

/* The glyph takes the button's colour rather than the icon component's own
   muted one: hover and the danger red are set on the button, and an SVG with a
   colour of its own would go on drawing itself grey through both. */
.detail__tool :deep(.sidebar-icon) {
  color: inherit;
}

.detail__tool:hover {
  background: var(--md-sys-state-hover-surface);
  color: var(--md-sys-color-on-surface);
}

.detail__tool--danger {
  color: var(--md-sys-color-error);
}

.detail__tool--danger:hover {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

/*
 * The pencil beside the one field this pane can change, and the offer to fill
 * it where it is empty. Both are drawn rather than revealed on hover: a finger
 * cannot hover, which is the rule the sidebar's row controls follow too.
 */
.detail__edit {
  margin-left: var(--md-spacing-2);
  padding: 0.1rem 0.25rem;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
  vertical-align: middle;
}

.detail__edit:hover {
  background: var(--md-sys-state-hover-surface);
  color: var(--md-sys-color-on-surface);
}

.detail__add {
  padding: 0;
  border: none;
  background: none;
  color: var(--md-sys-color-primary);
  font: inherit;
  font-size: inherit;
  text-align: left;
  cursor: pointer;
}

.detail__add:hover {
  text-decoration: underline;
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
  word-break: break-word;
  overflow-wrap: anywhere;
}

/*
 * In a narrow pane the label column is a third of the width, and an abstract
 * is left reading twenty characters to the line. Below that the label goes
 * above its value instead, which costs a line and buys the whole width.
 *
 * Twice over, because the two questions are not the same one. The media query
 * is the phone: a narrow *window*, where the panes are stacked and the pane is
 * as wide as the screen. The container query is a narrow *pane* in a wide
 * window, which is what dragging the grip to the right produces — and which
 * Safari only understood from 16, so the phone cannot be left to it.
 */
@media (max-width: 32rem) {
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

/* The same pill the sidebar draws. Outlined rather than filled, because
   nothing here is selected: these say what the item is tagged with, and the
   filled ones over there say what the list is being narrowed by. */
.detail__tag {
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-medium);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-label-small-size, 0.75rem);
  line-height: 1.35;
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
  background: var(--md-sys-state-hover-surface);
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
  word-break: break-word;
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
  word-break: break-word;
  overflow-wrap: anywhere;
}

.detail__error {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}
</style>
