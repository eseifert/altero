<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import { colorIndex, compareTags } from '@/items/tags'
import { useLibraryStore } from '@/stores/library'
import type { ItemEnvelope, SaveItem } from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'

/*
 * The item pane's Tags section: the item's tags, added, renamed and removed.
 *
 * The desktop's tags box drawn as the pills this pane already showed. A tag
 * is renamed by pressing it, removed with its cross, and added at the end,
 * with the library's tags offered as it is typed. Enter adds one and leaves
 * the box open for the next, as on the desktop; leaving the box adds what is
 * in it. Each change writes the whole list, one request after another, so a
 * second tag typed while the first is saving states the version the first
 * produced. If somebody else changed the tags meanwhile, the change is made
 * again on theirs: adding, removing and renaming are errands, not values.
 */

const { t } = useI18n()
const library = useLibraryStore()
const locale = useLocaleStore()

type Tag = { tag: string; type?: number }

const props = defineProps<{
  item: ItemEnvelope
  /** Whether this account may change this item, which the server decides. */
  editable: boolean
  /** Writes an edit and resolves once the server has answered. */
  save?: SaveItem
}>()

const colors = computed(() => colorIndex(library.tagColors))

const tags = computed<Tag[]>(() =>
  [...(props.item.data.tags ?? [])].sort((a, b) =>
    compareTags(a.tag, b.tag, colors.value, locale.formatting),
  ),
)

const canEdit = computed(() => props.editable && Boolean(props.save))

/* ---- Writing, one change after another ---- */

const failure = ref<string | null>(null)
let queue: Promise<void> = Promise.resolve()

/**
 * Apply ``change`` to the tags the item has when its turn comes.
 *
 * Worked out then rather than now, because the change before it may still be
 * on its way and the item it answers with is the one this one builds on.
 */
function write(change: (current: Tag[]) => Tag[]): Promise<void> {
  queue = queue.then(async () => {
    const current = props.item.data.tags ?? []
    const next = change(current)
    if (!props.save || same(current, next)) return
    failure.value = null
    try {
      // Changed elsewhere meanwhile: the same errand on the tags it has now,
      // which keeps whatever the other person added or took off.
      await props.save(
        { tags: next },
        {
          rebase: (fresh) => {
            const stored = fresh.data.tags ?? []
            const again = change(stored)
            return same(stored, again) ? null : { tags: again }
          },
        },
      )
      // The sidebar lists the library's tags, and this may have made or
      // emptied one.
      void library.loadTags().catch(() => {})
    } catch (thrown) {
      failure.value = thrown instanceof Error ? thrown.message : String(thrown)
    }
  })
  return queue
}

function same(a: Tag[], b: Tag[]): boolean {
  return a.length === b.length && a.every((tag, index) => tag.tag === b[index].tag && (tag.type ?? 0) === (b[index].type ?? 0))
}

/** Add ``names`` the item does not have yet, as tags somebody typed (type 0). */
function adding(names: string[]): (current: Tag[]) => Tag[] {
  return (current) => {
    const have = new Set(current.map((tag) => tag.tag))
    const added = [...new Set(names)].filter((name) => !have.has(name)).map((tag) => ({ tag }))
    return [...current, ...added]
  }
}

function remove(name: string): Promise<void> {
  return write((current) => current.filter((tag) => tag.tag !== name))
}

/** `Zotero.Item.replaceTag`: the new name takes the old one's place, as typed. */
function rename(from: string, to: string): Promise<void> {
  return write((current) => {
    if (current.some((tag) => tag.tag === to)) return current.filter((tag) => tag.tag !== from)
    return current.map((tag) => (tag.tag === from ? { tag: to } : tag))
  })
}

/* ---- The box being typed in: a new tag at the end, or one being renamed ---- */

/** The tag being renamed, or `''` for a new one; `null` when nothing is open. */
const open = ref<string | null>(null)
const draft = ref('')
const box = ref<HTMLInputElement | HTMLInputElement[] | null>(null)

function input(): HTMLInputElement | null {
  return (Array.isArray(box.value) ? box.value[0] : box.value) ?? null
}

async function start(name: string): Promise<void> {
  if (!canEdit.value) return
  open.value = name
  draft.value = name
  closeSuggestions()
  await nextTick()
  input()?.focus()
}

function close(): void {
  open.value = null
  draft.value = ''
  closeSuggestions()
}

/** Save what is in the box. ``stay`` keeps a new-tag box open for the next one. */
function commit(stay: boolean): void {
  const name = open.value
  if (name === null) return
  const value = draft.value.trim()
  if (name === '') {
    if (value) void write(adding([value]))
    if (stay && value) {
      draft.value = ''
      closeSuggestions()
      return
    }
  } else if (value !== name) {
    void (value ? rename(name, value) : remove(name))
  }
  close()
}

function keydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    if (!suggestions.value.length) return
    event.preventDefault()
    const step = event.key === 'ArrowDown' ? 1 : -1
    const count = suggestions.value.length
    active.value = active.value === null ? (step > 0 ? 0 : count - 1) : (active.value + step + count) % count
  } else if (event.key === 'Enter') {
    event.preventDefault()
    if (active.value !== null && suggestions.value[active.value]) {
      draft.value = suggestions.value[active.value]
    }
    commit(true)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    if (suggestions.value.length) closeSuggestions()
    else close()
  }
}

function blur(): void {
  commit(false)
}

/** Several lines pasted are several tags, as on the desktop. */
function paste(event: ClipboardEvent): void {
  const text = event.clipboardData?.getData('text') ?? ''
  const names = text
    .split(/\r\n?|\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (names.length < 2) return
  event.preventDefault()
  if (open.value) void remove(open.value)
  void write(adding(names))
  close()
}

/* ---- Completion from the library's tags ---- */

const found = ref<string[]>([])
const active = ref<number | null>(null)
let lookup: ReturnType<typeof setTimeout> | undefined
let lookupRun = 0

/** What is offered: tags the item lacks, those starting with the text first. */
const suggestions = computed(() => {
  if (open.value === null || !draft.value.trim()) return []
  const typed = draft.value.trim().toLocaleLowerCase()
  const have = new Set(tags.value.map((tag) => tag.tag))
  const starts = (name: string) => name.toLocaleLowerCase().startsWith(typed)
  return found.value
    .filter((name) => !have.has(name) && name !== draft.value.trim())
    .sort((a, b) => Number(starts(b)) - Number(starts(a)))
    .slice(0, 10)
})

function closeSuggestions(): void {
  clearTimeout(lookup)
  lookupRun += 1
  found.value = []
  active.value = null
}

function typed(): void {
  clearTimeout(lookup)
  active.value = null
  const text = draft.value
  if (!text.trim()) {
    found.value = []
    return
  }
  lookup = setTimeout(async () => {
    const run = ++lookupRun
    try {
      const entries = await library.findTags(text)
      if (run === lookupRun) found.value = entries.map((entry) => entry.tag)
    } catch {
      // Completion is a convenience: typing the whole tag still works.
    }
  }, 150)
}

function pick(name: string): void {
  draft.value = name
  commit(true)
}

const listId = computed(() => `tags-${props.item.key}-suggestions`)

function chipId(index: number): string {
  return `tags-${props.item.key}-${index}`
}

/* What was being typed belongs to the item it was opened on. */
watch(
  () => props.item.key,
  () => {
    close()
    failure.value = null
  },
)
</script>

<template>
  <section v-if="tags.length || canEdit" class="tags">
    <div class="tags__heading">
      <h3 class="tags__title">{{ t('Tags') }}</h3>
      <button
        v-if="canEdit"
        class="icon-button"
        type="button"
        :aria-label="t('Add Tag')"
        :title="t('Add Tag')"
        @click="start('')"
      >
        <AppIcon name="plus" :size="18" />
      </button>
    </div>

    <ul v-if="tags.length || open === ''" class="tags__list">
      <li
        v-for="(tag, index) in tags"
        :key="tag.tag"
        class="tags__tag"
        :class="{
          'tags__tag--automatic': tag.type === 1,
          'tags__tag--colored': colors.has(tag.tag),
          'tags__tag--open': open === tag.tag,
        }"
        :style="colors.has(tag.tag) ? { '--tag-color': colors.get(tag.tag)!.color } : undefined"
      >
        <span v-if="colors.has(tag.tag)" class="tags__swatch" aria-hidden="true"></span>
        <template v-if="open === tag.tag">
          <input
            ref="box"
            v-model="draft"
            class="tags__input"
            dir="auto"
            role="combobox"
            aria-autocomplete="list"
            :aria-expanded="suggestions.length > 0"
            :aria-controls="listId"
            :aria-activedescendant="active !== null ? `${listId}-${active}` : undefined"
            :aria-label="t('Rename tag')"
            @input="typed"
            @keydown="keydown"
            @blur="blur"
            @paste="paste"
          />
        </template>
        <template v-else>
          <button
            v-if="canEdit"
            :id="chipId(index)"
            class="tags__name"
            type="button"
            dir="auto"
            :title="tag.type === 1 ? t('Automatically added tag') : undefined"
            @click="start(tag.tag)"
          >
            {{ tag.tag }}<span v-if="tag.type === 1" class="visually-hidden">, {{ t('Automatically added tag') }}</span>
          </button>
          <span
            v-else
            :id="chipId(index)"
            class="tags__name"
            dir="auto"
            :title="tag.type === 1 ? t('Automatically added tag') : undefined"
          >
            {{ tag.tag }}<span v-if="tag.type === 1" class="visually-hidden">, {{ t('Automatically added tag') }}</span>
          </span>
          <button
            v-if="canEdit"
            class="tags__remove"
            type="button"
            :aria-label="t('Remove Tag')"
            :aria-describedby="chipId(index)"
            :title="t('Remove Tag')"
            @click="remove(tag.tag)"
          >
            <AppIcon name="close" :size="14" />
          </button>
        </template>
      </li>
      <li v-if="open === ''" class="tags__tag tags__tag--open">
        <input
          ref="box"
          v-model="draft"
          class="tags__input"
          dir="auto"
          role="combobox"
          aria-autocomplete="list"
          :aria-expanded="suggestions.length > 0"
          :aria-controls="listId"
          :aria-activedescendant="active !== null ? `${listId}-${active}` : undefined"
          :aria-label="t('Add Tag')"
          :placeholder="t('Add Tag')"
          @input="typed"
          @keydown="keydown"
          @blur="blur"
          @paste="paste"
        />
      </li>
    </ul>

    <!-- Pressed with the pointer held down, so the box keeps its focus and
         the blur that would save what was typed so far never happens. -->
    <ul v-show="suggestions.length" :id="listId" class="menu tags__suggestions" role="listbox">
      <li
        v-for="(name, index) in suggestions"
        :id="`${listId}-${index}`"
        :key="name"
        class="menu__item"
        :class="{ 'tags__suggestion--active': active === index }"
        role="option"
        :aria-selected="active === index"
        dir="auto"
        @mousedown.prevent="pick(name)"
      >
        {{ name }}
      </li>
    </ul>

    <p v-if="failure" class="tags__error" role="alert">{{ failure }}</p>
  </section>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.tags {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

/* The pane's section heading, with the desktop's add button at its end. */
.tags__heading {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  min-height: 1.75rem;
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
}

.tags__title {
  flex: 1;
  margin: 0;
  padding-bottom: 0.3rem;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.tags__heading .icon-button {
  width: 1.75rem;
  height: 1.75rem;
}

@media (pointer: coarse) {
  .tags__heading .icon-button {
    width: 2.5rem;
    height: 2.5rem;
  }
}

.tags__list {
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
.tags__tag {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  max-width: 100%;
  min-width: 0;
  padding-block: 0.2rem;
  padding-inline: 0.55rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-medium);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-label-small-size, 0.75rem);
  line-height: 1.35;
}

/* Added by a translator or an import rather than by a person, which the
   desktop marks with an icon of its own. */
.tags__tag--automatic {
  border-style: dashed;
}

.tags__tag:has(.tags__remove) {
  padding-inline-end: 0.2rem;
}

.tags__tag--open {
  border-color: var(--md-sys-color-primary);
  background: var(--md-sys-color-surface);
}

/* The colour the desktop gives the tag, as a dot: a dot keeps its contrast
   in both themes where tinted text or a filled pill would not. */
.tags__swatch {
  flex: none;
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--tag-color);
  box-shadow: 0 0 0 1px var(--md-sys-color-outline-variant);
}

.tags__name {
  overflow: hidden;
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
  text-overflow: ellipsis;
  white-space: nowrap;
}

button.tags__name {
  cursor: text;
}

button.tags__name:hover {
  color: var(--md-sys-color-on-surface);
  text-decoration: underline;
}

.tags__remove {
  display: grid;
  flex: none;
  place-items: center;
  width: 1.1rem;
  height: 1.1rem;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: none;
  color: inherit;
  cursor: pointer;
}

.tags__remove:hover {
  background: var(--md-sys-state-hover-surface);
  color: var(--md-sys-color-on-surface);
}

/* A finger needs more than a cross the size of the text beside it. */
@media (pointer: coarse) {
  .tags__tag {
    padding-block: 0.35rem;
  }

  .tags__remove {
    width: 1.75rem;
    height: 1.75rem;
  }
}

.tags__input {
  width: 9rem;
  min-width: 0;
  max-width: 100%;
  padding: 0;
  border: none;
  background: none;
  color: var(--md-sys-color-on-surface);
  font: inherit;
  outline: none;
}

.tags__suggestions {
  position: static;
  max-height: 14rem;
  overflow-y: auto;
}

.tags__suggestion--active {
  background: var(--md-sys-state-hover-surface);
}

.tags__error {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}
</style>
