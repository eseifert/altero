<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { formatDateTime } from '@/formats'
import { dateOrder } from '@/items/dates'
import { fieldLabel, itemTypeLabel, regularItemTypes, typeOutline } from '@/items/labels'
import type { ItemChanges, ItemEnvelope } from '@/stores/library'
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
  save?: (changes: ItemChanges) => Promise<unknown>
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

/** Whether the pane edits this item: it can be changed, and it has fields. */
const editing_ = computed(() => props.editable && outline.value !== null && Boolean(props.save))

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

const stamps = computed(() =>
  TIMESTAMPS.filter((name) => value(name) !== '').map((name) => ({
    name,
    text: formatDateTime(value(name)),
  })),
)

function href(name: string, text: string): string {
  return name === 'DOI' ? `https://doi.org/${text}` : text
}

/* ---- Editing a field in place ---- */

const editing = ref<string | null>(null)
const draft = ref('')
const busy = ref<string | null>(null)
const saved = ref<string | null>(null)
const failure = ref<{ name: string; message: string } | null>(null)
const input = ref<HTMLInputElement | HTMLTextAreaElement | null>(null)
let savedTimer: ReturnType<typeof setTimeout> | undefined

async function open(name: string): Promise<void> {
  if (!editing_.value || busy.value) return
  editing.value = name
  draft.value = value(name)
  failure.value = null
  await nextTick()
  const element = Array.isArray(input.value) ? input.value[0] : input.value
  element?.focus()
}

function cancel(): void {
  editing.value = null
}

async function commit(): Promise<void> {
  const name = editing.value
  if (name === null) return
  // Closed first, so that the blur which follows an Enter finds nothing to save.
  editing.value = null
  if (draft.value === value(name) || !props.save) return

  busy.value = name
  saved.value = null
  try {
    await props.save({ fields: { [name]: draft.value } })
    saved.value = name
    clearTimeout(savedTimer)
    savedTimer = setTimeout(() => (saved.value = null), 2000)
  } catch (thrown) {
    failure.value = { name, message: thrown instanceof Error ? thrown.message : String(thrown) }
  } finally {
    busy.value = null
  }
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
      typeFailure.value = thrown instanceof Error ? thrown.message : String(thrown)
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

/* What was being edited belongs to the item it was opened on. */
watch(
  () => props.item.key,
  () => {
    editing.value = null
    failure.value = null
    saved.value = null
    pendingType.value = null
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
          v-if="editing_"
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
      <template v-for="name in rows" :key="name">
        <dt :id="`info-${item.key}-${name}`">{{ fieldLabel(name) }}</dt>
        <dd :aria-busy="busy === name">
          <!-- Rights is set through the licence chooser, which knows the names a
               licence has to be stated in. -->
          <template v-if="name === 'rights' && rightsEditable">
            <span v-if="value('rights')">{{ value('rights') }}</span>
            <button
              v-if="value('rights')"
              class="info__pencil"
              type="button"
              :aria-label="t('Change the rights')"
              :title="t('Change the rights')"
              @click="emit('rights')"
            >
              <AppIcon name="edit" :size="12" />
            </button>
            <button v-else class="info__offer" type="button" @click="emit('rights')">
              {{ t('Not stated — say what it is') }}
            </button>
          </template>

          <template v-else-if="editing === name">
            <textarea
              v-if="MULTILINE.has(name)"
              ref="input"
              v-model="draft"
              class="info__input info__input--multiline"
              rows="4"
              dir="auto"
              :aria-labelledby="`info-${item.key}-${name}`"
              @keydown="keydown($event, name)"
              @blur="commit"
            ></textarea>
            <input
              v-else
              ref="input"
              v-model="draft"
              class="info__input"
              dir="auto"
              :aria-labelledby="`info-${item.key}-${name}`"
              @keydown="keydown($event, name)"
              @blur="commit"
            />
          </template>

          <template v-else-if="LINKS.has(name) && value(name)">
            <a :href="href(name, value(name))" target="_blank" rel="noopener noreferrer">{{ value(name) }}</a>
            <button
              v-if="editing_"
              class="info__pencil"
              type="button"
              :aria-label="t('Change')"
              :aria-describedby="`info-${item.key}-${name}`"
              @click="open(name)"
            >
              <AppIcon name="edit" :size="12" />
            </button>
          </template>

          <button
            v-else-if="editing_"
            class="info__value"
            :class="{ 'info__value--multiline': MULTILINE.has(name) }"
            type="button"
            dir="auto"
            :aria-labelledby="`info-${item.key}-${name}`"
            :disabled="busy !== null"
            @click="open(name)"
          >{{ value(name) }}</button>

          <span v-else dir="auto">{{ value(name) }}</span>

          <span v-if="DATES.has(name) && value(name) && editing !== name" class="info__order" aria-hidden="true">
            {{ dateOrder(value(name), locale.formatting) }}
          </span>
          <span v-if="saved === name" class="info__saved" role="status">{{ t('Saved.') }}</span>
          <p v-if="failure?.name === name" class="info__error" role="alert">{{ failure.message }}</p>
        </dd>
      </template>

      <template v-for="stamp in stamps" :key="stamp.name">
        <dt>{{ fieldLabel(stamp.name) }}</dt>
        <dd>{{ stamp.text }}</dd>
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
/* Drawn flush with plain text: the padding that gives a press somewhere to
   land is taken back out of the margin, so values that can and cannot be
   edited start at the same edge. */
.info__value {
  display: block;
  flex: 1 1 0;
  min-width: 0;
  min-height: 1.6em;
  margin: 0;
  margin-inline-start: -0.3rem;
  padding: 0.15rem 0.3rem;
  border: 1px solid transparent;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
  white-space: pre-wrap;
  cursor: text;
}

.info__value:hover {
  border-color: var(--md-sys-color-outline-variant);
}

.info__value:disabled {
  cursor: progress;
}

.info__value--multiline {
  min-height: 3.2em;
}

.info__input,
.info__type {
  box-sizing: border-box;
  flex: 1 1 0;
  min-width: 0;
  margin-inline-start: -0.3rem;
  padding: 0.15rem 0.3rem;
  border: 1px solid var(--md-sys-color-primary);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

.info__type {
  border-color: var(--md-sys-color-outline);
}

.info__input--multiline {
  resize: vertical;
}

.info__pencil {
  display: inline-grid;
  place-items: center;
  min-width: 1.5rem;
  min-height: 1.5rem;
  padding: 0.1rem 0.25rem;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
  vertical-align: middle;
}

.info__pencil:hover {
  background: var(--md-sys-state-hover-surface);
  color: var(--md-sys-color-on-surface);
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
