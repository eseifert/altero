<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppIcon from '@/components/AppIcon.vue'
import InfoPane from '@/components/InfoPane.vue'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import RelatedSection from '@/components/RelatedSection.vue'
import SidebarIcon from '@/components/SidebarIcon.vue'
import TagEditor from '@/components/TagEditor.vue'
import { exportable } from '@/exportformats'
import { itemTypeLabel } from '@/items/labels'
import { getItemTitle } from '@/items/titles'
import { cleanBibliography, cleanNote } from '@/sanitize'
import type { ItemEnvelope, SaveItem } from '@/stores/library'

const { t } = useI18n()

/* The note editor is most of a text editor, and only a note needs it: it is
   fetched the first time one is opened, not with the library. */
const NotePane = defineAsyncComponent(() => import('@/components/NotePane.vue'))

const props = defineProps<{
  item: ItemEnvelope
  children: ItemEnvelope[]
  libraryId: number
  fileUrl: (key: string, options?: { download?: boolean }) => string
  /** Whether this account may change the library, which the server decides. */
  writable?: boolean
  /** Whether the server would accept taking this item out of the library.
   *  Narrower than `writable` for a member of a group who may add to it and
   *  not remove from it. */
  removable?: boolean
  /** Whether this library has a My Publications at all: a personal one does,
   *  a group does not, and publishing is refused there. */
  publishable?: boolean
  /** Whether the list behind this pane is the My Publications view. The
   *  desktop client shows a child item's publishing button only there, and so
   *  does this: elsewhere a note's place in the list is its parent's business. */
  inPublicationsView?: boolean
  /** Writes an edit of this item, for the Info pane. Absent where nothing
   *  may be edited, which leaves every field as text. */
  save?: SaveItem
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
  /** Make a note under this item, which the view opens. */
  addNote: []
}>()

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

/** Whether the Info pane edits this item. Not in the trash, which the desktop
 *  draws read-only and the server refuses to change. */
const editable = computed(() => Boolean(props.writable) && !trashed.value)

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

const title = computed(
  () => getItemTitle(props.item) || t(props.item.data.itemType === 'note' ? 'Note' : '(untitled)'),
)

const isAttachment = computed(
  () =>
    props.item.data.itemType === 'attachment' &&
    typeof props.item.data.linkMode === 'string' &&
    props.item.data.linkMode.startsWith('imported'),
)

const isNote = computed(() => props.item.data.itemType === 'note')

/** Whether this item takes notes under it: a regular item, as on the desktop. */
const takesNotes = computed(
  () => editable.value && !['note', 'attachment', 'annotation'].includes(props.item.data.itemType),
)

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

const info = ref<InstanceType<typeof InfoPane> | null>(null)
const heading = ref<HTMLElement | null>(null)
const notePane = ref<{ focus: () => void } | null>(null)
/** A note just made wants the cursor, which waits for the editor to arrive. */
const noteAutofocus = ref(false)
watch(
  () => props.item.key,
  () => (noteAutofocus.value = false),
)

defineExpose({
  /** Put the cursor in the note, as for a note just made. */
  focusNote: () => {
    if (notePane.value) notePane.value.focus()
    else noteAutofocus.value = true
  },
  /** Open one of the Info pane's fields for typing, as for a new item. */
  editField: (name: string) => info.value?.edit(name),
  /** Move the keyboard into the pane, at its heading, as Enter in the list does. */
  focus: () => heading.value?.focus(),
})

function childTitle(child: ItemEnvelope): string {
  if (child.data.itemType === 'note') {
    return getItemTitle(child) || t('Note')
  }
  return getItemTitle(child) || child.data.filename || child.key
}
</script>

<template>
  <article class="detail">
    <header class="detail__header">
      <ItemTypeIcon :item-type="item.data.itemType" :size="22" />
      <div class="detail__headings">
        <h2 ref="heading" class="detail__title" tabindex="-1">{{ title }}</h2>
        <p class="detail__type">{{ itemTypeLabel(item.data.itemType) }}</p>
      </div>
      <button class="icon-button detail__close" type="button" :aria-label="t('Close details')" @click="emit('close')">
        <AppIcon name="close" :size="22" />
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
    <div v-if="showsTools || offersPublishing || offersExport" class="detail__tools toolbar">
      <button
        v-if="showsTools"
        class="icon-button"
        type="button"
        :aria-label="t('Move or copy…')"
        :title="t('Move or copy…')"
        @click="emit('move')"
      >
        <SidebarIcon name="move" :size="22" />
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
          class="icon-button"
          type="button"
          :aria-label="child ? t('Show in My Publications') : t('Add to My Publications…')"
          :title="child ? t('Show in My Publications') : t('Add to My Publications…')"
          @click="emit('publish')"
        >
          <SidebarIcon name="publish" :size="22" />
        </button>
        <button
          v-else
          class="icon-button"
          type="button"
          :aria-label="child ? t('Hide from My Publications') : t('Remove from My Publications')"
          :title="child ? t('Hide from My Publications') : t('Remove from My Publications')"
          @click="emit('unpublish')"
        >
          <SidebarIcon name="unpublish" :size="22" />
        </button>
      </template>

      <!-- Writing this item out as a file. Not behind `showsTools`: exporting
           is a read, so it is offered on a child item and in a library this
           account may only read. -->
      <button
        v-if="offersExport"
        class="icon-button"
        type="button"
        :aria-label="t('Export…')"
        :title="t('Export…')"
        @click="emit('export')"
      >
        <SidebarIcon name="export" :size="22" />
      </button>

      <template v-if="showsTools">
        <!-- Throwing away is a removal, which is what a member who may add to
             a group and not remove from it is not offered. -->
        <button
          v-if="!trashed"
          v-show="removable !== false"
          class="icon-button"
          type="button"
          :aria-label="t('Move to trash')"
          :title="t('Move to trash')"
          @click="emit('trash')"
        >
          <SidebarIcon name="trash" :size="22" />
        </button>
        <template v-else>
          <!-- Zotero's own words for this, and a key of its own: "Restore"
               alone is also what the settings page calls putting an archive
               back, and one message for the two had German telling somebody
               their item was about to be replayed from a backup. -->
          <button
            class="icon-button"
            type="button"
            :aria-label="t('Restore to Library')"
            :title="t('Restore to Library')"
            @click="emit('restore')"
          >
            <SidebarIcon name="restore" :size="22" />
          </button>
          <!-- A bin with a cross through it rather than the bin: this is the
               one thing here that cannot be undone, and it must not look like
               the errand that can. -->
          <button
            v-if="removable !== false"
            class="icon-button icon-button--danger"
            type="button"
            :aria-label="t('Delete')"
            :title="t('Delete')"
            @click="emit('remove')"
          >
            <SidebarIcon name="deleteforever" :size="22" />
          </button>
        </template>
      </template>
    </div>

    <NotePane
      v-if="isNote && editable && save"
      ref="notePane"
      :key="item.key"
      :item="item"
      :editable="editable"
      :save="save"
      :image-url="(key) => fileUrl(key)"
      :autofocus="noteAutofocus"
    />
    <div v-else-if="isNote" class="card__inset detail__note" v-html="cleanNote(item.data.note)"></div>


    <InfoPane ref="info" :item="item" :editable="editable" :save="save" @rights="emit('rights')" />

    <p v-if="isAttachment" class="detail__actions">
      <a class="detail__link" :href="fileUrl(item.key)" target="_blank" rel="noopener">{{ t('Open file') }}</a>
      <a class="detail__link" :href="fileUrl(item.key, { download: true })">{{ t('Download') }}</a>
    </p>

    <TagEditor :item="item" :editable="editable" :save="save" />

    <RelatedSection :item="item" :editable="editable" @open="emit('open', $event)" />

    <section v-if="children.length || takesNotes" class="detail__section">
      <div class="detail__heading-row">
        <h3 class="detail__heading detail__heading--in-row">{{ t('Attachments and notes') }}</h3>
        <button
          v-if="takesNotes"
          class="icon-button detail__add"
          type="button"
          :aria-label="t('Add Note')"
          :title="t('Add Note')"
          @click="emit('addNote')"
        >
          <AppIcon name="plus" :size="18" />
        </button>
      </div>
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
      <div v-else-if="bibliography" class="card__inset detail__bib" v-html="cleanBibliography(bibliography)"></div>
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

/* Standing on its own rather than in the toolbar: it dismisses the pane
   instead of acting on what is in it. */
.detail__close {
  border-radius: var(--md-sys-shape-corner-small);
}

@media (pointer: coarse) {
  .detail__close {
    width: 2.5rem;
    height: 2.5rem;
  }

}

/* A row of glyphs, drawn like the tools over the item list, because they are
   the same errands reaching the same items -- one row picked out here, several
   picked out there. Each says what it is in `aria-label` and in `title`. The
   toolbar around them is what says they can be pressed; this adds only the
   wrapping a narrow pane needs. */
.detail__tools {
  flex-wrap: wrap;
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

/* A heading with its own errand beside it, drawn as the Related section draws
   one: the rule runs under both. */
.detail__heading-row {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
}

.detail__heading--in-row {
  flex: 1;
  border-bottom: none;
}

.detail__add {
  width: 1.75rem;
  height: 1.75rem;
}

@media (pointer: coarse) {
  .detail__add {
    width: 2.5rem;
    height: 2.5rem;
  }
}

.detail__section {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
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
