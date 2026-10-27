<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import ConflictNotice from '@/components/ConflictNotice.vue'
import CreatorEditor from '@/components/CreatorEditor.vue'
import { formatDateTime } from '@/formats'
import { holdsStoredFile } from '@/items/attachments'
import { dateOrder } from '@/items/dates'
import { fieldLabel, itemTypeLabel, regularItemTypes, typeOutline } from '@/items/labels'
import { EditConflict } from '@/stores/library'
import type { CreatorEntry, ItemEnvelope, SaveItem } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

/*
 * The item pane's Info section: the item's type and fields, edited in place.
 *
 * Drawn the way the desktop's item pane draws it -- every field of the type,
 * in the schema's order, so that an empty one can be filled -- when the item
 * can be changed, and only what the item says when it cannot. A value is
 * edited where it stands: a press opens it, Enter or leaving it saves, and
 * Escape puts it back. Each save is one request, stating the version it
 * replaces, and the pane says when it has landed.
 */

const { t } = useI18n()
const locale = useLocaleStore()

const props = defineProps<{
  item: ItemEnvelope
  /** Whether this account may change this item, which the server decides. */
  editable: boolean
  /** Writes an edit and resolves once the server has answered. */
  save?: SaveItem
}>()

const emit = defineEmits<{
  /** The licence chooser, which is how a published work's terms are set. */
  rights: []
}>()

/** Properties drawn elsewhere in the pane, or of no interest to a reader. */
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
  'inPublications',
  'note',
  'md5',
  'mtime',
  'linkMode',
  'dateAdded',
  'dateModified',
])

/** Fields edited in a box several lines tall, as the desktop draws them. */
const MULTILINE = new Set(['abstractNote', 'extra'])

/** Fields that are addresses as well as text, and stay links until edited. */
const LINKS = new Set(['url', 'DOI'])

/** Whose dates are drawn with the order Zotero read them in. */
const DATES = new Set(['date'])

/** The two the server stamps: shown in the reader's own zone, never edited. */
const TIMESTAMPS = ['dateAdded', 'dateModified']

const outline = computed(() => typeOutline(props.item.data.itemType))

const isAttachment = computed(() => props.item.data.itemType === 'attachment')

/** What the desktop's attachment box lets a person type: the rest it shows. */
const ATTACHMENT_EDITED = new Set(['title', 'filename'])

/** Whether the pane edits this item: it can be changed, and it has fields. An
 *  attachment has no outline in the schema -- its content is a file or a link
 *  -- and is edited as the attachment box edits it. */
const editing_ = computed(
  () => props.editable && Boolean(props.save) && (outline.value !== null || isAttachment.value),
)

/** Whether ``name`` is typed into here, rather than only shown. */
function fieldEditable(name: string): boolean {
  return editing_.value && (!isAttachment.value || ATTACHMENT_EDITED.has(name))
}

function value(name: string): string {
  const found = props.item.data[name]
  return typeof found === 'string' ? found : ''
}

/** Item types with no Rights field, which is the whole of that list. */
const WITHOUT_RIGHTS = new Set(['note', 'attachment', 'annotation'])

/**
 * Whether the licence chooser is offered. Not tied to the schema having
 * arrived: a published work's terms are set here whatever else the pane can
 * do yet, as they were before the rest of the fields could be edited.
 */
const rightsEditable = computed(
  () => props.editable && !WITHOUT_RIGHTS.has(props.item.data.itemType),
)

const rows = computed(() => {
  const order = outline.value?.fields ?? []
  if (editing_.value && isAttachment.value) {
    // The attachment box's rows: the title, a stored file's name -- the one
    // field here the schema does not list -- and the address and the date it
    // was read, where it has them.
    return [
      'title',
      ...(holdsStoredFile(props.item) ? ['filename'] : []),
      ...['url', 'accessDate'].filter((name) => value(name) !== ''),
    ]
  }
  if (editing_.value) {
    return order.filter((name) => !HIDDEN.has(name))
  }
  const present = Object.keys(props.item.data).filter(
    (name) => !HIDDEN.has(name) && value(name) !== '',
  )
  // "Not stated" is exactly what somebody publishing a work wants to change,
  // so an empty Rights keeps its row where the chooser is offered.
  if (rightsEditable.value && !present.includes('rights')) present.push('rights')
  // What the item says, in the schema's order where the schema is known.
  return present.sort((a, b) => {
    const first = order.indexOf(a)
    const second = order.indexOf(b)
    return (first < 0 ? order.length : first) - (second < 0 ? order.length : second)
  })
})

const creators = computed<CreatorEntry[]>(() =>
  Array.isArray(props.item.data.creators) ? (props.item.data.creators as CreatorEntry[]) : [],
)

/** Creators follow the title, where the desktop draws them; first, without one. */
const creatorsAfter = computed(() => (rows.value.includes('title') ? 'title' : null))

const stamps = computed(() =>
  TIMESTAMPS.filter((name) => value(name) !== '').map((name) => ({
    name,
    text: formatDateTime(value(name)),
  })),
)

function href(name: string, text: string): string {
  return name === 'DOI' ? `https://doi.org/${text}` : text
}

/** A field's name as the pane shows it; the schema names every field but the file's. */
function labelOf(name: string): string {
  return name === 'filename' ? t('Filename') : fieldLabel(name)
}

/* ---- Editing a field in place ---- */

const editing = ref<string | null>(null)
const draft = ref('')
/** What the field said when it was opened. The item can change under an open
 *  field -- a change made elsewhere arriving -- and the draft is kept. */
let openedWith = ''
const busy = ref<string | null>(null)
const saved = ref<string | null>(null)
const failure = ref<{ name: string; message: string } | null>(null)
/** A value typed here while somebody else changed the same field. */
const conflict = ref<{ name: string; mine: string } | null>(null)
const input = ref<HTMLTextAreaElement | HTMLTextAreaElement[] | null>(null)
/** The height of the value being edited, which its box starts at. */
const openHeight = ref(0)
let savedTimer: ReturnType<typeof setTimeout> | undefined

function box(): HTMLTextAreaElement | null {
  return (Array.isArray(input.value) ? input.value[0] : input.value) ?? null
}

/** Fit the box to what it holds, never shorter than the value it opened from. */
function grow(): void {
  const element = box()
  if (!element) return
  element.style.height = 'auto'
  const borders = element.offsetHeight - element.clientHeight
  element.style.height = `${Math.max(element.scrollHeight + borders, openHeight.value)}px`
}

async function open(name: string): Promise<void> {
  if (!fieldEditable(name) || busy.value) return
  const shown = document.getElementById(`info-${props.item.key}-${name}-value`)
  openHeight.value = shown?.offsetHeight ?? 0
  editing.value = name
  draft.value = value(name)
  openedWith = draft.value
  failure.value = null
  conflict.value = null
  await nextTick()
  grow()
  box()?.focus()
}

function cancel(): void {
  editing.value = null
}

async function commit(): Promise<void> {
  const name = editing.value
  if (name === null) return
  // Closed first, so that the blur which follows an Enter finds nothing to save.
  editing.value = null
  // A line break pasted into a field of one line is a space, as on the desktop.
  if (!MULTILINE.has(name)) draft.value = draft.value.replace(/\r?\n/g, ' ')
  if (name === 'filename' && !renaming()) return
  if (draft.value === value(name) || !props.save) return
  // Changed elsewhere while it was open: saving now would write over that
  // without anybody having seen it, so the reader is asked, as after a 412.
  if (value(name) !== openedWith) {
    conflict.value = { name, mine: draft.value }
    return
  }

  await write(name, draft.value)
}

/* ---- Renaming a file ---- */

/** What the desktop's attachment box takes for an extension. */
const EXTENSION = /\.\w{1,10}$/

function extension(name: string): string {
  return EXTENSION.exec(name)?.[0] ?? ''
}

/** A new name whose extension differs from the file's, waiting for the reader's word. */
const pendingName = ref<{ name: string; from: string; to: string } | null>(null)

/**
 * The attachment box's rules for a new file name, applied to the draft.
 *
 * Trimmed, and an empty one puts the old name back. A name typed without an
 * extension keeps the file's. A different extension is asked about first,
 * since the file may then open in a different application: the reader keeps
 * the old one or uses the new. Whether to go on and save is the answer.
 */
function renaming(): boolean {
  const name = draft.value.trim()
  const old = value('filename')
  if (!name || name === old) return false
  const from = extension(old)
  const to = extension(name)
  draft.value = !to && from ? name + from : name
  if (to && from && to !== from) {
    pendingName.value = { name, from, to }
    return false
  }
  return true
}

function settleName(keep: boolean): void {
  const pending = pendingName.value
  pendingName.value = null
  if (!pending) return
  void write('filename', keep ? pending.name.replace(EXTENSION, pending.from) : pending.name)
}

async function write(name: string, text: string): Promise<void> {
  if (!props.save) return
  busy.value = name
  saved.value = null
  conflict.value = null
  try {
    await props.save({ fields: { [name]: text } })
    saved.value = name
    clearTimeout(savedTimer)
    savedTimer = setTimeout(() => (saved.value = null), 2000)
  } catch (thrown) {
    if (thrown instanceof EditConflict) {
      conflict.value = { name, mine: text }
    } else {
      failure.value = { name, message: thrown instanceof Error ? thrown.message : String(thrown) }
    }
  } finally {
    busy.value = null
  }
}

/** The reader's answer to a conflict: their own value written over, or let go. */
function resolve(keepMine: boolean): void {
  const found = conflict.value
  conflict.value = null
  if (found && keepMine) void write(found.name, found.mine)
}

function keydown(event: KeyboardEvent, name: string): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancel()
  } else if (event.key === 'Enter' && (!MULTILINE.has(name) || event.shiftKey)) {
    // Shift+Enter saves a box several lines tall, as on the desktop, where a
    // plain Enter is a new line.
    event.preventDefault()
    void commit()
  }
}

/* ---- Changing the type ---- */

const types = computed(() =>
  regularItemTypes()
    .map((name) => ({ name, label: itemTypeLabel(name) }))
    .sort((a, b) => a.label.localeCompare(b.label, locale.formatting)),
)

/** A change waiting for the reader's word, with the fields it would lose. */
const pendingType = ref<{ itemType: string; lost: string[] } | null>(null)
const typeFailure = ref<string | null>(null)
const typeSelect = ref<HTMLSelectElement | null>(null)

async function changeType(itemType: string, discard?: string[]): Promise<void> {
  if (!props.save || itemType === props.item.data.itemType) return
  typeFailure.value = null
  busy.value = 'itemType'
  try {
    await props.save(discard ? { itemType, discard } : { itemType })
    pendingType.value = null
  } catch (thrown) {
    const lost = thrown instanceof ApiError ? thrown.data?.fields : undefined
    if (thrown instanceof ApiError && thrown.status === 409 && Array.isArray(lost)) {
      pendingType.value = { itemType, lost: lost.map(String) }
    } else {
      typeFailure.value =
        thrown instanceof EditConflict
          ? t('Changed elsewhere while you were editing.')
          : thrown instanceof Error
            ? thrown.message
            : String(thrown)
      revertType()
    }
  } finally {
    busy.value = null
  }
}

function revertType(): void {
  pendingType.value = null
  if (typeSelect.value) typeSelect.value.value = props.item.data.itemType
}

defineExpose({
  /** Open ``name`` for typing, as a press on its value does. */
  edit: open,
})

/* What was being edited belongs to the item it was opened on. */
watch(
  () => props.item.key,
  () => {
    editing.value = null
    failure.value = null
    conflict.value = null
    saved.value = null
    pendingType.value = null
    pendingName.value = null
    typeFailure.value = null
  },
)

</script>

<template>
  <div class="info-pane">
    <dl class="info">
      <dt :id="`info-${item.key}-itemType`">{{ fieldLabel('itemType') }}</dt>
      <dd>
        <select
          v-if="editing_ && !isAttachment"
          ref="typeSelect"
          class="info__type"
          :value="item.data.itemType"
          :aria-labelledby="`info-${item.key}-itemType`"
          :disabled="busy !== null"
          @change="changeType(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="type in types" :key="type.name" :value="type.name">{{ type.label }}</option>
        </select>
        <span v-else>{{ itemTypeLabel(item.data.itemType) }}</span>
        <p v-if="typeFailure" class="info__error" role="alert">{{ typeFailure }}</p>
      </dd>
    </dl>

    <!-- Zotero's own words, from its item pane: the fields are named before
         anything is lost, and nothing is until the reader says so. -->
    <div
      v-if="pendingType"
      class="card__inset info__confirm"
      role="alertdialog"
      :aria-label="t('Change Item Type')"
    >
      <p>{{ t('Are you sure you want to change the item type?') }}</p>
      <p>{{ t('The following fields will be lost:') }}</p>
      <ul>
        <li v-for="name in pendingType.lost" :key="name">{{ fieldLabel(name) }}</li>
      </ul>
      <div class="info__buttons">
        <AppButton variant="text" @click="revertType">{{ t('Cancel') }}</AppButton>
        <AppButton @click="changeType(pendingType.itemType, pendingType.lost)">{{ t('Change') }}</AppButton>
      </div>
    </div>

    <dl class="info">
      <CreatorEditor
        v-if="creatorsAfter === null && !isAttachment"
        :item-key="item.key"
        :creators="creators"
        :roles="outline?.creatorTypes ?? []"
        :editable="editing_"
        :save="save"
      />
      <template v-for="name in rows" :key="name">
        <dt :id="`info-${item.key}-${name}`">{{ labelOf(name) }}</dt>
        <dd :aria-busy="busy === name">
          <!-- Rights is set through the licence chooser, which knows the names a
               licence has to be stated in; it is pressed like any other value. -->
          <template v-if="name === 'rights' && rightsEditable">
            <button
              v-if="value('rights')"
              class="info__value"
              type="button"
              dir="auto"
              :aria-label="t('Change the rights')"
              :title="t('Change the rights')"
              @click="emit('rights')"
            >{{ value('rights') }}</button>
            <button v-else class="info__offer" type="button" @click="emit('rights')">
              {{ t('Not stated — say what it is') }}
            </button>
          </template>

          <!-- One box for every field, the height of the value it replaces and
               growing as it fills, so that opening a field moves nothing. A
               field of one line takes no line break: Enter saves it. -->
          <textarea
            v-else-if="editing === name"
            ref="input"
            v-model="draft"
            class="info__input"
            rows="1"
            dir="auto"
            :aria-multiline="MULTILINE.has(name)"
            :aria-labelledby="`info-${item.key}-${name}`"
            :style="{ minHeight: `${openHeight}px` }"
            @input="grow"
            @keydown="keydown($event, name)"
            @blur="commit"
          ></textarea>

          <button
            v-else-if="fieldEditable(name)"
            :id="`info-${item.key}-${name}-value`"
            class="info__value"
            :class="{ 'info__value--multiline': MULTILINE.has(name) }"
            type="button"
            dir="auto"
            :aria-labelledby="`info-${item.key}-${name}`"
            :disabled="busy !== null"
            @click="open(name)"
          >{{ value(name) }}</button>

          <a
            v-else-if="LINKS.has(name)"
            :href="href(name, value(name))"
            target="_blank"
            rel="noopener noreferrer"
            dir="auto"
          >{{ value(name) }}</a>

          <span v-else dir="auto" :class="{ info__fixed: editing_ }">{{ value(name) }}</span>

          <!-- An address is opened from a button of its own, beside a value that
               is edited like any other. -->
          <a
            v-if="fieldEditable(name) && LINKS.has(name) && value(name) && editing !== name"
            class="info__open"
            :href="href(name, value(name))"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="href(name, value(name))"
            :title="href(name, value(name))"
          >
            <AppIcon name="open" :size="20" />
          </a>
          <span v-if="DATES.has(name) && value(name) && editing !== name" class="info__order" aria-hidden="true">
            {{ dateOrder(value(name), locale.formatting) }}
          </span>
          <span v-if="saved === name" class="info__saved" role="status">{{ t('Saved.') }}</span>
          <div
            v-if="name === 'filename' && pendingName"
            class="card__inset info__confirm"
            role="alertdialog"
            :aria-label="labelOf('filename')"
          >
            <p>
              {{ t('Are you sure you want to change the file extension from “{from}” to “{to}”?', pendingName) }}
            </p>
            <p>{{ t('If you change the extension, the file may open in a different application.') }}</p>
            <div class="info__buttons">
              <AppButton variant="text" @click="settleName(true)">
                {{ t('Keep {extension}', { extension: pendingName.from }) }}
              </AppButton>
              <AppButton @click="settleName(false)">{{ t('Use {extension}', { extension: pendingName.to }) }}</AppButton>
            </div>
          </div>
          <p v-if="failure?.name === name" class="info__error" role="alert">{{ failure.message }}</p>
          <ConflictNotice
            v-if="conflict?.name === name"
            :id="`info-${item.key}-${name}-conflict`"
            :mine="conflict.mine"
            :theirs="value(name)"
            @mine="resolve(true)"
            @theirs="resolve(false)"
          />
        </dd>
        <CreatorEditor
          v-if="name === creatorsAfter && !isAttachment"
          :item-key="item.key"
          :creators="creators"
          :roles="outline?.creatorTypes ?? []"
          :editable="editing_"
          :save="save"
        />
      </template>

      <!-- Stamped by the server, never typed: drawn quieter than what can be
           edited, where anything can, and with nothing to press. -->
      <template v-for="stamp in stamps" :key="stamp.name">
        <dt>{{ fieldLabel(stamp.name) }}</dt>
        <dd :class="{ info__fixed: editing_ }">{{ stamp.text }}</dd>
      </template>
    </dl>
  </div>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.info {
  display: grid;
  grid-template-columns: minmax(5.5rem, 8rem) 1fr;
  gap: 0.2rem var(--md-spacing-3);
  align-items: start;
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}

/* The label's padding is the value's, so a label and the first line of its
   value share a line whether or not the value can be pressed. */
.info dt {
  padding-block: calc(0.15rem + 1px);
  color: var(--md-sys-color-on-surface-variant);
}

/* A value takes the room it has; what is said about it -- Zotero's `y m d`,
   "Saved." -- sits beside it, and a refusal goes underneath. */
.info dd {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--md-spacing-2);
  min-width: 0;
  margin: 0;
  padding-block: calc(0.15rem + 1px);
  word-break: break-word;
  overflow-wrap: anywhere;
}

.info dd:has(.info__value, .info__input, .info__type) {
  padding-block: 0;
}

.info dd[aria-busy='true'] {
  animation: info-pulse var(--md-sys-motion-duration-long2, 500ms) ease-in-out infinite alternate;
}

@keyframes info-pulse {
  from {
    opacity: 1;
  }

  to {
    opacity: 0.55;
  }
}

.info-pane {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

/* Between the type and the fields: it is about the whole item. The inset
   comes from `surfaces.css`, like the note and the citation beside it. */

.info__confirm p,
.info__confirm ul {
  margin-block: 0 var(--md-spacing-2);
}

.info__buttons {
  display: flex;
  justify-content: flex-end;
  gap: var(--md-spacing-2);
}

/*
 * A value that can be edited is drawn as the text it is, and says it can be
 * pressed only by the hover a pointer gives it and the outline a keyboard
 * does. An empty one keeps its height so there is somewhere to press.
 */
/*
 * A value that can be edited is drawn as the text it is, and says it can be
 * pressed by the frame a pointer brings up over it and the outline a keyboard
 * does. Its box, when it opens, has the same font, line, padding and border,
 * so nothing around it moves. The padding that gives a press somewhere to land
 * is taken back out of the margin, so values that can and cannot be edited
 * start at the same edge. An empty value keeps a line's height.
 */
.info__value,
.info__input {
  box-sizing: border-box;
  display: block;
  flex: 1 1 0;
  min-width: 0;
  min-height: calc(1.4em + 0.3rem + 2px);
  margin: 0;
  margin-inline-start: -0.3rem;
  padding: 0.15rem 0.3rem;
  border: 1px solid transparent;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  line-height: 1.4;
  text-align: start;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.info__value {
  cursor: text;
}

.info__value:hover {
  border-color: var(--md-sys-color-outline);
}

.info__value:disabled {
  cursor: progress;
}

.info__value--multiline {
  min-height: calc(2.8em + 0.3rem + 2px);
}

.info__input {
  border-color: var(--md-sys-color-primary);
  background: var(--md-sys-color-surface);
  overflow: hidden;
  resize: none;
}

.info__type {
  box-sizing: border-box;
  flex: 1 1 0;
  min-width: 0;
  margin-inline-start: -0.3rem;
  padding: 0.15rem 0.3rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

/* An address opens from here: a control of its own, outlined like the
   controls are, so it does not read as part of the text beside it. */
.info__open {
  display: inline-grid;
  flex: none;
  place-items: center;
  align-self: center;
  width: 1.9rem;
  height: 1.9rem;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-small);
  color: var(--md-sys-color-primary);
}

.info__open:hover {
  border-color: var(--md-sys-color-primary);
  background: var(--md-sys-state-hover-surface);
}

/* What the server stamps, in a pane where the rest can be edited. */
.info__fixed {
  color: var(--md-sys-color-on-surface-variant);
}



.info__offer {
  padding: 0;
  border: none;
  background: none;
  color: var(--md-sys-color-primary);
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.info__offer:hover {
  text-decoration: underline;
}

/* Zotero's `y m d`: what it read the date as, quietly, beside it. */
.info__order {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
  letter-spacing: 0.05em;
}

.info__saved {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}

.info__error {
  flex-basis: 100%;
  margin: 0.2rem 0 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}

/* Label and value side by side, as the desktop's item pane keeps them, down
   to a column too narrow for both; only then does the label go above. A
   type's twenty fields stacked would be forty lines, most of them empty. */
@container (max-width: 20rem) {
  .info {
    grid-template-columns: 1fr;
    gap: 0.1rem;
  }

  .info dd {
    margin-block-end: 0.4rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .info dd[aria-busy='true'] {
    animation: none;
    opacity: 0.7;
  }
}
</style>
