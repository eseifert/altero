<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import ConflictNotice from '@/components/ConflictNotice.vue'
import { useCarry } from '@/dragging'
import { fieldLabel } from '@/items/labels'
import { EditConflict } from '@/stores/library'
import type { CreatorEntry, SaveItem } from '@/stores/library'

/*
 * An item's creators, as rows of the Info pane: the desktop's creator rows.
 *
 * Each row is a role and a name -- a last and a first, or one full name for an
 * institution -- edited where it stands, like every other value in the pane.
 * The whole list is one property of the item, so every change writes the list:
 * when focus leaves a creator, or on Enter; at once for a role, a removal, a
 * move or a switch between one field and two. A row emptied of its names goes
 * when it is saved, and a row added and never named is never written, as on
 * the desktop -- the server refuses a creator with no name at all.
 *
 * Reordered by dragging the grip, which a finger does after a short hold, or
 * from the row's options, which is the way in for a keyboard.
 */

const { t } = useI18n()

const props = defineProps<{
  itemKey: string
  creators: CreatorEntry[]
  /** The roles this item type allows, its primary one first. */
  roles: string[]
  editable: boolean
  save?: SaveItem
}>()

interface Row {
  /** Stable across moves, for Vue and for the drop targets. */
  id: number
  creatorType: string
  single: boolean
  lastName: string
  firstName: string
  /** Added here and not written yet. */
  fresh: boolean
}

let nextId = 0

function rowOf(creator: CreatorEntry): Row {
  const single = creator.name !== undefined
  return {
    id: nextId++,
    creatorType: creator.creatorType,
    single,
    lastName: single ? (creator.name ?? '') : (creator.lastName ?? ''),
    firstName: single ? '' : (creator.firstName ?? ''),
    fresh: false,
  }
}

function blank(role: string, single: boolean): Row {
  return { id: nextId++, creatorType: role, single, lastName: '', firstName: '', fresh: true }
}

const rows = ref<Row[]>([])
const failure = ref<string | null>(null)
/** The list written here while somebody else changed the creators. */
const conflict = ref<CreatorEntry[] | null>(null)
const busy = ref(false)

/** Read the stored creators, and give an editable item with none a row to fill. */
function reset(): void {
  rows.value = props.creators.map(rowOf)
  if (!rows.value.length && props.editable && props.roles.length) {
    rows.value = [blank(props.roles[0], false)]
  }
}

watch(
  () => props.itemKey,
  () => (conflict.value = null),
)

watch(() => [props.itemKey, props.creators, props.editable, props.roles] as const, reset, {
  immediate: true,
  deep: true,
})

function entry(row: Row): CreatorEntry | null {
  const last = row.lastName.trim()
  const first = row.firstName.trim()
  if (row.single) return last ? { creatorType: row.creatorType, name: last } : null
  if (!last && !first) return null
  return { creatorType: row.creatorType, firstName: first, lastName: last }
}

/** What the rows say, as the API writes it: unnamed rows left out. */
function written(): CreatorEntry[] {
  return rows.value.map(entry).filter((found): found is CreatorEntry => found !== null)
}

async function commit(): Promise<void> {
  const list = written()
  if (!props.save || JSON.stringify(list) === JSON.stringify(props.creators)) return
  await write(list)
}

async function write(list: CreatorEntry[]): Promise<void> {
  if (!props.save) return
  busy.value = true
  failure.value = null
  conflict.value = null
  try {
    await props.save({ creators: list })
  } catch (thrown) {
    // The rows go back to what is stored, which after a conflict is the
    // other person's list; the notice holds this one.
    if (thrown instanceof EditConflict) conflict.value = list
    else failure.value = thrown instanceof Error ? thrown.message : String(thrown)
    reset()
  } finally {
    busy.value = false
  }
}

function resolve(keepMine: boolean): void {
  const list = conflict.value
  conflict.value = null
  if (list && keepMine) void write(list)
}

/** A list of creators in one line, last name first, for the conflict notice. */
function summary(list: CreatorEntry[]): string {
  return list
    .map((creator) =>
      creator.name ?? [creator.lastName, creator.firstName].filter(Boolean).join(', '),
    )
    .join('; ')
}

/* ---- Names, saved when the creator is left ---- */

function leave(event: FocusEvent, row: Row): void {
  const next = event.relatedTarget as Node | null
  const element = document.querySelector(`[data-creator="${row.id}"]`)
  // Moving from the last name to the first is still the same creator.
  if (next && element?.contains(next)) return
  void commit()
}

function keydown(event: KeyboardEvent): void {
  if (event.key === 'Enter') {
    event.preventDefault()
    ;(event.target as HTMLElement).blur()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    reset()
    ;(event.target as HTMLElement).blur()
  }
}

/* ---- Rows added, removed, moved and switched ---- */

async function add(after: number): Promise<void> {
  const above = rows.value[after]
  const row = blank(above?.creatorType ?? props.roles[0], above?.single ?? false)
  rows.value.splice(after + 1, 0, row)
  await nextTick()
  document.querySelector<HTMLInputElement>(`[data-creator="${row.id}"] input`)?.focus()
}

function remove(index: number): void {
  closeMenu()
  const [gone] = rows.value.splice(index, 1)
  if (gone.fresh) {
    if (!rows.value.length) reset()
    return
  }
  void commit()
}

function move(from: number, to: number): void {
  closeMenu()
  if (to < 0 || to >= rows.value.length || from === to) return
  const [row] = rows.value.splice(from, 1)
  rows.value.splice(to, 0, row)
  void commit()
}

/**
 * One field or two, as `itemBox.switchCreatorMode` does it: into one, the
 * first name goes before the last; into two, the last word is the last name
 * and whatever comes before it the first.
 */
function switchMode(row: Row): void {
  closeMenu()
  if (row.single) {
    const parts = /(.*?)[ ]*([^ ]+[ ]*)$/.exec(row.lastName)
    if (parts && parts[2] && parts[2] !== row.lastName) {
      row.firstName = parts[1]
      row.lastName = parts[2]
    }
    row.single = false
  } else {
    if (row.firstName) row.lastName = `${row.firstName} ${row.lastName}`
    row.firstName = ''
    row.single = true
  }
  void commit()
}

function changeRole(row: Row, role: string): void {
  row.creatorType = role
  void commit()
}

/* ---- The options menu ---- */

const menuFor = ref<number | null>(null)

function toggleMenu(id: number): void {
  menuFor.value = menuFor.value === id ? null : id
}

function closeMenu(): void {
  menuFor.value = null
}

function outside(event: PointerEvent): void {
  if (!(event.target as Element | null)?.closest('.creator__options')) closeMenu()
}

onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))

/* ---- Dragging by the grip ---- */

const carry = useCarry<number>()

function grab(event: PointerEvent, index: number): void {
  const row = rows.value[index]
  carry.begin(
    event,
    { label: `${row.lastName} ${row.firstName}`.trim(), data: index },
    {
      accepts: (target) => target !== `creator-${row.id}`,
      onDrop: (target) => {
        const to = rows.value.findIndex((each) => `creator-${each.id}` === target)
        move(rows.value.indexOf(row), to)
      },
    },
  )
}

const carried = computed(() =>
  carry.carrying.value ? rows.value[carry.carrying.value.data]?.id : null,
)

/** The name a read-only row shows: last, first, as the desktop shows it. */
function shown(row: Row): string {
  if (row.single || !row.firstName) return row.lastName
  return row.lastName ? `${row.lastName}, ${row.firstName}` : row.firstName
}

/** Every role this type allows, and the row's own if a laxer client set another. */
function rolesFor(row: Row): string[] {
  return props.roles.includes(row.creatorType) ? props.roles : [row.creatorType, ...props.roles]
}
</script>

<template>
  <template v-for="(row, index) in rows" :key="row.id">
    <dt
      class="creator__label"
      :class="{ 'creator--carried': carried === row.id, 'creator--target': carry.target.value === `creator-${row.id}` }"
      :data-drop="editable ? `creator-${row.id}` : undefined"
    >
      <template v-if="editable">
        <span
          class="creator__grip"
          aria-hidden="true"
          @pointerdown="grab($event, index)"
        >
          <AppIcon name="grip" :size="18" />
        </span>
        <select
          :id="`creator-${itemKey}-${row.id}-role`"
          class="creator__role"
          :value="row.creatorType"
          :aria-label="shown(row) || t('full name')"
          :disabled="busy"
          @change="changeRole(row, ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="role in rolesFor(row)" :key="role" :value="role">{{ fieldLabel(role) }}</option>
        </select>
      </template>
      <template v-else>{{ fieldLabel(row.creatorType) }}</template>
    </dt>

    <dd
      class="creator"
      :class="{ 'creator--carried': carried === row.id, 'creator--target': carry.target.value === `creator-${row.id}` }"
      :data-creator="row.id"
      :data-drop="editable ? `creator-${row.id}` : undefined"
      :aria-busy="busy"
    >
      <template v-if="editable">
        <span class="creator__names">
          <input
            v-model="row.lastName"
            class="creator__name"
            dir="auto"
            :placeholder="row.single ? t('full name') : t('last')"
            :aria-label="row.single ? t('full name') : t('last')"
            :aria-describedby="`creator-${itemKey}-${row.id}-role`"
            @keydown="keydown"
            @blur="leave($event, row)"
          />
          <input
            v-if="!row.single"
            v-model="row.firstName"
            class="creator__name"
            dir="auto"
            :placeholder="t('first')"
            :aria-label="t('first')"
            :aria-describedby="`creator-${itemKey}-${row.id}-role`"
            @keydown="keydown"
            @blur="leave($event, row)"
          />
        </span>
        <span class="creator__tools">
          <button
            class="icon-button"
            type="button"
            :aria-label="t('Remove Creator')"
            :title="t('Remove Creator')"
            :disabled="busy"
            @click="remove(index)"
          >
            <AppIcon name="minus" :size="18" />
          </button>
          <button
            class="icon-button"
            type="button"
            :aria-label="t('Add Creator')"
            :title="t('Add Creator')"
            :disabled="busy"
            @click="add(index)"
          >
            <AppIcon name="plus" :size="18" />
          </button>
          <span class="creator__options">
            <button
              class="icon-button"
              type="button"
              aria-haspopup="menu"
              :aria-expanded="menuFor === row.id"
              :aria-label="t('More Options…')"
              :title="t('More Options…')"
              :disabled="busy"
              @click="toggleMenu(row.id)"
              @keydown.escape="closeMenu"
            >
              <AppIcon name="more" :size="18" />
            </button>
            <ul v-if="menuFor === row.id" class="menu creator__menu" role="menu" @keydown.escape="closeMenu">
              <li role="none">
                <button class="menu__item" role="menuitem" type="button" @click="switchMode(row)">
                  {{ row.single ? t('Switch to Two Fields') : t('Switch to Single Field') }}
                </button>
              </li>
              <li role="none">
                <button class="menu__item" role="menuitem" type="button" :disabled="index === 0" @click="move(index, index - 1)">
                  {{ t('Move Up') }}
                </button>
              </li>
              <li role="none">
                <button
                  class="menu__item"
                  role="menuitem"
                  type="button"
                  :disabled="index === rows.length - 1"
                  @click="move(index, index + 1)"
                >
                  {{ t('Move Down') }}
                </button>
              </li>
            </ul>
          </span>
        </span>
      </template>
      <span v-else dir="auto">{{ shown(row) }}</span>
      <p v-if="failure && index === rows.length - 1" class="creator__error" role="alert">{{ failure }}</p>
    </dd>
  </template>
  <dd v-if="conflict" class="creator__conflict">
    <ConflictNotice
      :id="`creator-${itemKey}-conflict`"
      :mine="summary(conflict)"
      :theirs="summary(creators)"
      @mine="resolve(true)"
      @theirs="resolve(false)"
    />
  </dd>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.creator__label {
  display: flex;
  align-items: center;
  gap: 0.15rem;
  min-width: 0;
}

/* Only a pointer or a finger picks a creator up; a keyboard moves it from the
   options, so the grip is not a stop on the way through the row. */
.creator__grip {
  display: grid;
  flex: none;
  place-items: center;
  margin-inline-start: -0.4rem;
  color: var(--md-sys-color-on-surface-variant);
  cursor: grab;
  touch-action: none;
}

.creator__role {
  min-width: 0;
  max-width: 100%;
  padding: 0.1rem 0.2rem;
  border: 1px solid transparent;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.creator__role:hover {
  border-color: var(--md-sys-color-outline);
}

.creator {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--md-spacing-1, 0.25rem);
  min-width: 0;
  margin: 0;
}

/* The names give up room before the tools do, so a creator keeps to one line
   in a pane of ordinary width. */
.creator__names {
  display: flex;
  flex: 1 1 0;
  gap: var(--md-spacing-2);
  min-width: 7rem;
}

/* Drawn like every other value that can be edited: as text, with a frame
   under the pointer and a coloured one while it is being typed in. */
.creator__name {
  box-sizing: border-box;
  flex: 1 1 0;
  min-width: 0;
  margin-inline-start: -0.3rem;
  padding: 0.15rem 0.3rem;
  border: 1px solid transparent;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  line-height: 1.4;
}

.creator__name:hover {
  border-color: var(--md-sys-color-outline);
}

.creator__name:focus {
  border-color: var(--md-sys-color-primary);
  background: var(--md-sys-color-surface);
  outline: none;
}

.creator__name::placeholder {
  color: var(--md-sys-color-on-surface-variant);
}

/* Three to a row, and a row per creator: smaller than the pane's other icon
   buttons where a pointer aims, and the full size where a finger does, even
   if that sends them to a line of their own. */
.creator__tools {
  display: flex;
  flex: none;
}

.creator__tools .icon-button {
  width: 1.75rem;
  height: 1.75rem;
}

@media (pointer: coarse) {
  .creator__tools .icon-button {
    width: 2.5rem;
    height: 2.5rem;
  }
}

.creator__options {
  position: relative;
}

.creator__menu {
  inset-block-start: 100%;
  inset-inline-end: 0;
}

.creator--carried {
  opacity: 0.45;
}

/* Where a dropped creator lands: a line along the top of its row. */
.creator--target {
  box-shadow: inset 0 2px 0 var(--md-sys-color-primary);
}

.creator__conflict {
  grid-column: 1 / -1;
  margin: 0;
}

.creator__error {
  flex-basis: 100%;
  margin: 0.2rem 0 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size, 0.8rem);
}
</style>
