<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { placesFor } from '@/collectionplaces'
import AppButton from '@/components/AppButton.vue'
import CollectionDialog from '@/components/CollectionDialog.vue'
import CollectionSettingsDialog from '@/components/CollectionSettingsDialog.vue'
import ShareDialog from '@/components/ShareDialog.vue'
import CollectionTree from '@/components/CollectionTree.vue'
import ExportDialog from '@/components/ExportDialog.vue'
import ItemDestinationDialog from '@/components/ItemDestinationDialog.vue'
import ItemDetail from '@/components/ItemDetail.vue'
import ItemSelection from '@/components/ItemSelection.vue'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'
import PublicationsDialog from '@/components/PublicationsDialog.vue'
import RightsDialog from '@/components/RightsDialog.vue'
import SidebarIcon from '@/components/SidebarIcon.vue'
import PaneSplitter from '@/components/PaneSplitter.vue'
import TagDialog from '@/components/TagDialog.vue'
import { useCarry } from '@/dragging'
import { exportable } from '@/exportformats'
import { fieldLabel, loadLabels } from '@/items/labels'
import { libraryLabel } from '@/librarylabel'
import { DETAIL, readWidth, SIDEBAR, storeWidth, type PaneWidth } from '@/panewidths'
import { useAuthStore } from '@/stores/auth'
import {
  useLibraryStore,
  type CollectionNode,
  type ItemEnvelope,
  type TagEntry,
} from '@/stores/library'
import { useLocaleStore } from '@/stores/locale'
import { useShareStore } from '@/stores/shares'

const { t } = useI18n()

const library = useLibraryStore()
const locales = useLocaleStore()
const shares = useShareStore()
/* The account's own username, which is what its public page is addressed by,
   and its id, which is the only thing a member restricted to their own items
   can be compared against -- `createdByUser` on an item is an id. What may be
   *done* to a library is still the server's answer and not this one's; this
   decides only whether to draw a control the server would refuse. */
const auth = useAuthStore()

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

/*
 * The widths the reader last chose, for the two columns that have a choice.
 *
 * The layout follows a drag frame by frame; the store does not. One drag is
 * dozens of updates and a single decision, and `localStorage` is synchronous,
 * so the writing waits out a pause exactly as the search field does.
 */
const sidebarWidth = ref(readWidth(SIDEBAR))
const detailWidth = ref(readWidth(DETAIL))

/** Per pane: the pause that is running, and the width it is about to store. */
const widthTimers = new Map<string, { timer: ReturnType<typeof setTimeout>; width: number }>()

/* A ref cannot be passed in from the template -- it arrives unwrapped, as the
   number it holds -- so the two panes get a setter each over one debounce. */
function remember(pane: PaneWidth, width: number): void {
  clearTimeout(widthTimers.get(pane.key)?.timer)
  widthTimers.set(pane.key, {
    width,
    timer: setTimeout(() => {
      widthTimers.delete(pane.key)
      storeWidth(pane, width)
    }, 250),
  })
}

/*
 * Nothing this screen started outlives it.
 *
 * Both pauses here are a quarter of a second long, which is ample time to leave
 * the screen in: a search typed and then navigated away from would run its
 * query against a library nobody is looking at any more, and the width from a
 * drag that had not settled would be lost. So the search is dropped and the
 * widths are written out at once -- the difference being that one is a
 * question about what to show and the other is a decision already made.
 *
 * In the tests this is what stops a timer from one test firing during the
 * next: the store write it carried made the earlier test's Pinia active again,
 * and the next test's `useStore()` then handed back a store its own component
 * had never heard of. See the note in `src/test-setup.ts`.
 */
onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  for (const [key, pending] of widthTimers) {
    clearTimeout(pending.timer)
    storeWidth(key === SIDEBAR.key ? SIDEBAR : DETAIL, pending.width)
  }
  widthTimers.clear()
})

function resizeSidebar(width: number): void {
  sidebarWidth.value = width
  remember(SIDEBAR, width)
}

function resizeDetail(width: number): void {
  detailWidth.value = width
  remember(DETAIL, width)
}

/* The detail pane exists only when there is something in it. An empty third
   column would take a fifth of the width to say nothing, and the item list is
   what the width is for. With more than one row picked out it holds a count and
   the errands rather than an item's fields -- see `ItemSelection`. */
const showDetail = computed(() => library.selection.length > 0 && library.libraryId !== null)

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
  if (library.scope === 'publications')
    return t('Nothing in this library has been published yet.')
  if (library.scope === 'recentlyread') return t('Nothing has been read here lately.')
  if (library.scope === 'duplicates') return t('No two items here look like the same work.')
  if (library.scope === 'unfiled') return t('Everything here is filed in a collection.')
  if (library.collectionKey) return t('This collection is empty.')
  /* A group fills up when a member syncs into it, and that member need not be
     whoever is reading this -- nor, in a read-only group, can it be. */
  if (library.library?.type === 'group') return t('Nothing has been added to this group yet.')
  return t('Nothing here yet. Point the Zotero desktop app at this server and sync.')
})

/* What the middle pane is headed with: the row the sidebar has selected, in
   the same words the sidebar used for it. It named the account before the
   sidebar started calling the personal library "My Library", so the two
   disagreed about what was being shown. */
const heading = computed(() => {
  if (library.collectionName) return library.collectionName
  /* Spelt out rather than looked up in a map: the catalogue is built by
     reading the translation calls out of the source, and a key that arrives in
     a variable is a key `locales.node.spec.ts` cannot see. */
  switch (library.scope) {
    case 'trash':
      return t('Trash')
    case 'all':
      return t('All items')
    case 'publications':
      return t('My Publications')
    case 'recentlyread':
      return t('Recently Read')
    case 'duplicates':
      return t('Duplicate Items')
    case 'unfiled':
      return t('Unfiled Items')
  }
  return library.library ? libraryLabel(library.library) : t('Library')
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
  /* Who is reading, for the one question the store cannot answer without it:
     a member restricted to their own items is compared against `createdByUser`,
     which is an account id. */
  library.viewerId = auth.user?.id ?? null
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

/*
 * Whether the search is open, which is whether it is a field or a glyph.
 *
 * Closed is the resting state: a library is read far more often than it is
 * searched, and eighteen rems of empty field over a list is eighteen rems the
 * heading and the tools do not have. It opens when pressed and closes when it
 * is left with nothing in it — never while it holds a term, since the term is
 * the only thing on screen that explains the list underneath it.
 */
const searching = ref(false)

async function openSearch(): Promise<void> {
  searching.value = true
  // The field does not exist until this has been drawn, and a search that
  // opens without the cursor in it is a control pressed twice.
  await nextTick()
  searchField.value?.focus()
}

function closeSearchIfEmpty(): void {
  if (!searchText.value) searching.value = false
}

/* Escape empties a field that holds something and closes one that does not,
   which is how every search that folds away behaves. It stops there rather
   than reaching the list, whose own Escape clears the selection. */
function escapeSearch(): void {
  if (searchText.value) {
    clearSearch()
    return
  }
  searching.value = false
}

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
 * Making, changing and removing a collection.
 *
 * One pending action at a time, held here rather than in the tree: the tree
 * recurses into itself, so state kept in it would be per level, and there is
 * only ever one of these on screen.
 *
 * Making one opens a dialog, because it takes two answers -- where, and what to
 * call it -- and the first of those is a place in a tree that the dialog has to
 * show. Changing one opens another, for the same reason: a name and a place.
 * Removing one asks in place, as everything else here does, because it takes no
 * answer beyond yes -- and it asks under the tree, where the collection it is
 * about can still be seen.
 */
type Pending =
  | { kind: 'create'; parent: CollectionNode | null }
  | { kind: 'settings'; target: CollectionNode }
  | { kind: 'delete'; target: CollectionNode }

const pending = ref<Pending | null>(null)
const busy = ref(false)
const collectionError = ref<string | null>(null)

/* The heading goes above the first group and nowhere else, so an account with
   no groups is not told it has none. */
const firstGroup = computed(
  () => library.libraries.find((entry) => entry.type === 'group')?.id ?? null,
)

/** Whether the list is showing the whole of ``id`` -- no collection, no view. */
function showingWholeOf(id: number): boolean {
  return id === library.libraryId && !library.collectionKey && library.scope === 'top'
}

/*
 * The library row is the library's top level, so pressing it means that.
 *
 * Opening another library already lands there; pressing the one that is open
 * has to say so, or a reader who has walked into a collection has no way back
 * to the whole library except the browser's back button.
 */
async function openLibrary(id: number): Promise<void> {
  if (id === library.libraryId) {
    await library.selectScope('top')
    return
  }
  await library.openLibrary(id)
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

function startSettings(target: CollectionNode): void {
  pending.value = { kind: 'settings', target }
  collectionError.value = null
}

/* ---- Sharing one collection by link ---- */

/** The collection whose links are open, or null. */
const sharing = ref<CollectionNode | null>(null)

function startSharing(target: CollectionNode): void {
  /* The settings dialog goes: two dialogs at once is two top layers, and the
     one underneath cannot be reached anyway. */
  pending.value = null
  sharing.value = target
  shares.forget()
  if (library.libraryId !== null) {
    void shares.load(library.libraryId)
  }
}

function stopSharing(): void {
  sharing.value = null
  shares.forget()
}

async function createShare(terms: {
  subcollections: boolean
  files: boolean
  expires: string | null
}): Promise<void> {
  if (!sharing.value || library.libraryId === null) return
  await shares.create(library.libraryId, sharing.value.key, terms)
}

async function revokeShare(shareId: number): Promise<void> {
  if (library.libraryId === null) return
  await shares.revoke(library.libraryId, shareId)
}

function startDelete(target: CollectionNode): void {
  pending.value = { kind: 'delete', target }
  collectionError.value = null
}

/*
 * The collection whose settings are open, and everywhere it could be moved to.
 *
 * The library heads the list, because "no parent" is not an absence to a
 * reader -- it is the library, which is the row the top-level collections hang
 * from. What is left out is this collection and everything under it.
 */
const editing = computed(() => (pending.value?.kind === 'settings' ? pending.value.target : null))

const places = computed(() =>
  placesFor(
    library.collections,
    library.library ? libraryLabel(library.library) : t('Library'),
    editing.value?.key,
  ),
)

async function submitSettings(changes: {
  name: string
  parentCollection: string | null
}): Promise<void> {
  const current = pending.value
  if (current?.kind !== 'settings') return

  if (!changes.name) {
    collectionError.value = t('A collection needs a name.')
    return
  }
  await run(() => library.updateCollection(current.target.key, changes))
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

/*
 * What can be done to items and to a collection, and the two ways of asking.
 *
 * Carrying rows somewhere is the quick way and the one the desktop client
 * teaches: onto a collection files them there, onto the library takes them out
 * of the collection being shown, onto the trash throws them away, and onto
 * another library copies them. A collection can be carried too — onto another
 * collection to sit inside it, onto the library to come back to the top level,
 * onto the trash to be asked about deleting it.
 *
 * A carry holds whatever was picked out. Dragging a row that is part of the
 * selection carries the whole selection; dragging one that is not carries that
 * row alone and leaves the selection alone with it. What is under the pointer
 * says which it is — a title, or a count — so a carry never takes anything the
 * reader cannot see it holding.
 *
 * Every one of those is also a button or a key, because a control only a
 * pointer can reach is a control some readers do not have -- `Delete` on a row
 * trashes it, the detail pane names the same errands in words, and a
 * collection's settings dialog moves it by naming where it goes.
 *
 * Nothing here decides a permission for itself: a row is only carried where
 * `writable` says the server would accept the write.
 */
type Cargo =
  | { kind: 'items'; items: ItemEnvelope[] }
  | { kind: 'collection'; node: CollectionNode }

const carry = useCarry<Cargo>()

const itemError = ref<string | null>(null)

/** The keys of the rows being carried, so they can be shown leaving. */
const carriedKeys = computed(() => {
  const cargo = carry.carrying.value?.data
  if (!cargo) return new Set<string>()
  return new Set(
    cargo.kind === 'items' ? cargo.items.map((item) => item.key) : [cargo.node.key],
  )
})

/** Whether ``target`` is the row underneath the carry, and so the one to light. */
function lit(target: string): boolean {
  return carry.carrying.value !== null && carry.target.value === target
}

/** Whether ``node`` is ``key`` or holds it, however deep. */
function holds(node: CollectionNode, key: string): boolean {
  return node.key === key || node.children.some((child) => holds(child, key))
}

/**
 * Whether a row will take what is being carried.
 *
 * A row that would refuse the drop does not light up, which is the whole of
 * what this is for: it is easier to say no by never offering than to explain a
 * refusal after the fact. A collection cannot go inside itself or inside
 * anything under it -- that is a branch nothing can reach afterwards -- and it
 * cannot cross into another library at all, which would be a copy of a
 * collection and everything filed in it.
 */
function accepts(target: string): boolean {
  const cargo = carry.carrying.value?.data
  if (!cargo || !library.writable) return false

  const [kind, value] = [target.slice(0, target.indexOf(':')), target.slice(target.indexOf(':') + 1)]

  if (cargo.kind === 'items') {
    if (kind === 'library') return Number(value) !== library.libraryId || Boolean(library.collectionKey)
    /* Only a work, only one that is not published already, and not one in the
       trash: a note or an attachment reaches My Publications with the item it
       belongs to, and the published list hides trashed items, so publishing
       one would flag something nobody can see.

       And only ever one at a time. Publishing is a wizard whose answers depend
       on the item in front of it -- which of its files go, which of its notes,
       what its Rights field already says -- so a selection has no one set of
       answers to give it. The row does not light up rather than the wizard
       opening on a question it cannot ask. */
    if (kind === 'publications') {
      const item = cargo.items.length === 1 ? cargo.items[0] : null
      if (!item) return false
      return !item.data.parentItem && !item.data.inPublications && !item.data.deleted
    }
    return kind === 'collection' || kind === 'trash'
  }

  if (kind === 'library') {
    return Number(value) === library.libraryId && cargo.node.data.parentCollection !== false
  }
  if (kind === 'trash') return true
  return kind === 'collection' && !holds(cargo.node, value)
}

/* Whatever the failure was, it is shown above the list rather than swallowed:
   a carry that quietly did nothing is indistinguishable from a bug. */
async function runOnItem(action: () => Promise<void>): Promise<void> {
  itemError.value = null
  try {
    await action()
  } catch (thrown) {
    itemError.value = thrown instanceof Error ? thrown.message : String(thrown)
  }
}

/*
 * Begin carrying something.
 *
 * What is being carried is closed over rather than read back when it lands:
 * the carry is cleared as the pointer is released, which is a moment before
 * the drop is worked out.
 */
function startCarry(cargo: Cargo, label: string, event: PointerEvent): void {
  if (!library.writable) return
  carry.begin(event, { label, data: cargo }, {
    accepts,
    onDrop: (target, { modified }) => void drop(cargo, target, { modified }),
  })
}

/**
 * Begin carrying a row, and whatever else is picked out with it.
 *
 * A row already in the selection carries the whole selection; one that is not
 * carries itself alone, and leaves the selection where it was. Picking rows out
 * is what a click is for, and a drag that quietly changed the selection on the
 * way past would leave the reader with a different list than they had — the
 * carry says what it holds, which is what the label under the pointer is for.
 */
function carryItem(item: ItemEnvelope, event: PointerEvent): void {
  const items =
    library.selectionKeys.includes(item.key) && library.selectionKeys.length > 1
      ? [...library.selectedItems]
      : [item]
  const label =
    items.length > 1 ? t('{count} item | {count} items', items.length) : titleOf(items[0])
  startCarry({ kind: 'items', items }, label, event)
}

function carryCollection(node: CollectionNode, event: PointerEvent): void {
  startCarry({ kind: 'collection', node }, node.data.name, event)
}

/**
 * What a drop means, once the row it landed on is known.
 *
 * Kept apart from the gesture so that the dialogs can call the same code: what
 * "file this here" does must not depend on how it was asked for.
 */
async function drop(cargo: Cargo, target: string, { modified = false } = {}): Promise<void> {
  const kind = target.slice(0, target.indexOf(':'))
  const value = target.slice(target.indexOf(':') + 1)

  if (cargo.kind === 'items') {
    const keys = cargo.items.map((item) => item.key)
    if (kind === 'trash') {
      await runOnItem(() => library.trashItems(keys))
      return
    }
    if (kind === 'publications') {
      /* The one drop that asks before it acts, and the desktop client asks
         too: what goes with the work and under what licence are not things a
         gesture can say, and publishing is not undone by dragging it back.
         `accepts` has already refused anything but a single work. */
      await startPublishing(cargo.items[0])
      return
    }
    if (kind === 'collection') {
      /* Adding rather than moving, which is Zotero's rule: a collection is not
         a folder and an item can be in several. Shift is how a mouse says
         otherwise; a finger says it in the dialog instead. */
      const from = library.collectionKey
      const remove = modified && from && from !== value ? [from] : []
      await runOnItem(() => library.fileItems(keys, { add: [value], remove }))
      return
    }
    if (Number(value) !== library.libraryId) {
      await runOnItem(() => library.copyItems(keys, Number(value)))
      return
    }
    const from = library.collectionKey
    if (from) await runOnItem(() => library.fileItems(keys, { remove: [from] }))
    return
  }

  const node = cargo.node
  if (kind === 'trash') {
    /* Asked rather than done: a collection carries subcollections, and a
       finger that landed on the wrong row should not be able to remove one. */
    startDelete(node)
    return
  }
  if (kind === 'collection') {
    await runOnItem(() => library.updateCollection(node.key, { parentCollection: value }))
    return
  }
  await runOnItem(() => library.updateCollection(node.key, { parentCollection: null }))
}

/*
 * Publishing a work, and taking it back out.
 *
 * The wizard is `PublicationsDialog`; what is held here is which item it is
 * about and what that item has, because the answers it offers depend on the
 * item: there is no point offering to include files that are not there, and
 * the Rights field can only be kept if it says something. The children are
 * fetched when the dialog opens rather than read off the row — a row carries a
 * title and a count, not the attachments themselves.
 */
const publishing = ref<ItemEnvelope | null>(null)
const publishingChildren = ref<ItemEnvelope[]>([])

/** Attachments this server holds the bytes of. A link is neither, and goes
 *  along regardless; a linked file cannot be published at all. */
const publishHasFiles = computed(() =>
  publishingChildren.value.some(
    (child) =>
      child.data.itemType === 'attachment' &&
      typeof child.data.linkMode === 'string' &&
      child.data.linkMode.startsWith('imported'),
  ),
)

const publishHasNotes = computed(() =>
  publishingChildren.value.some((child) => child.data.itemType === 'note'),
)

const publishHasRights = computed(() => Boolean(publishing.value?.data.rights))

async function startPublishing(item: ItemEnvelope): Promise<void> {
  /* A note or an attachment is shown on its own, with nothing to ask: what to
     include and under what licence are the work's questions, and the work has
     already answered them. The desktop client's button does the same — it
     publishes the child and opens no wizard. */
  if (item.data.parentItem) {
    await runOnItem(() =>
      library.publishItem(item.key, {
        includeFiles: false,
        includeNotes: false,
        license: null,
        keepRights: true,
      }),
    )
    return
  }

  itemError.value = null
  try {
    publishingChildren.value = await library.childrenOf(item.key)
  } catch {
    /* The dialog opens either way, with both checkboxes disabled: it asks
       about files and notes, and "we could not find out" is closer to "there
       are none" than to refusing to publish the work at all. */
    publishingChildren.value = []
  }
  /* Opened only once the answer is in. A dialog that opens first and enables
     its checkboxes a moment later is a race the reader can lose: a tick lands
     on a disabled box, nothing happens, and the files are left behind on a
     page that has already moved on. */
  publishing.value = item
}

/*
 * The Rights field, which is the one field this interface writes.
 *
 * It is here rather than in the wizard because it is not a publishing
 * question: an item says what its rights are whether or not it is published.
 * What makes it worth having at all is publishing — the wizard sets a licence
 * once, and the desktop client's own wizard refuses to run twice on the same
 * item, so without this the licence could never be corrected here.
 */
const editingRights = ref<ItemEnvelope | null>(null)

async function submitRights(rights: string): Promise<void> {
  const item = editingRights.value
  if (!item) return

  itemBusy.value = true
  itemError.value = null
  try {
    await library.editItem(item.key, { rights })
    editingRights.value = null
  } catch (thrown) {
    itemError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    itemBusy.value = false
  }
}

async function submitPublication(terms: {
  includeFiles: boolean
  includeNotes: boolean
  license: string | null
  keepRights: boolean
}): Promise<void> {
  const item = publishing.value
  if (!item) return

  itemBusy.value = true
  itemError.value = null
  try {
    await library.publishItem(item.key, terms)
    publishing.value = null
    publishingChildren.value = []
  } catch (thrown) {
    itemError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    itemBusy.value = false
  }
}

/*
 * Deleting from the keyboard, and unpublishing from it.
 *
 * `Delete` on a row does what dropping it on the trash does, except in two
 * views where the row means something else: in the trash the item is already
 * there and the key means for good, and in My Publications it means take it
 * out of the list — which is what the desktop client's Delete does there too.
 * Both ask first. One cannot be undone at all; the other cannot be undone by
 * pressing anything, only by going through the wizard again.
 */
const removing = ref<ItemEnvelope[]>([])
const unpublishing = ref<ItemEnvelope | null>(null)
const emptying = ref(false)
const itemBusy = ref(false)

function askToRemove(items: ItemEnvelope[]): void {
  if (!items.length) return
  removing.value = items
  unpublishing.value = null
  emptying.value = false
  itemError.value = null
}

/**
 * Take an item out of My Publications: the question, or the act.
 *
 * A work is asked about, because it takes its notes and files out with it and
 * because putting it back is the whole wizard again. A child is hidden on the
 * spot — that is one flag on one item, and showing it again is one press.
 */
async function askToUnpublish(item: ItemEnvelope): Promise<void> {
  if (item.data.parentItem) {
    await runOnItem(() => library.unpublishItem(item.key))
    return
  }
  unpublishing.value = item
  removing.value = []
  emptying.value = false
  itemError.value = null
}

function askToEmpty(): void {
  emptying.value = true
  removing.value = []
  unpublishing.value = null
  itemError.value = null
}

function cancelRemoval(): void {
  removing.value = []
  unpublishing.value = null
  emptying.value = false
}

async function deleteItems(items: ItemEnvelope[]): Promise<void> {
  itemBusy.value = true
  await runOnItem(() => library.deleteItems(items.map((item) => item.key)))
  itemBusy.value = false
  cancelRemoval()
}

async function emptyTrash(): Promise<void> {
  itemBusy.value = true
  await runOnItem(async () => void (await library.emptyTrash()))
  itemBusy.value = false
  cancelRemoval()
}

async function unpublishItem(item: ItemEnvelope): Promise<void> {
  itemBusy.value = true
  await runOnItem(() => library.unpublishItem(item.key))
  itemBusy.value = false
  cancelRemoval()
}

/**
 * `Delete` on a row: the trash, or -- in the trash and in My Publications --
 * the question that view's Delete asks instead.
 *
 * On the whole selection when the row pressed is part of it, and on that row
 * alone when it is not, which is the rule the drag follows. My Publications is
 * the exception: taking something out of it is per work, so the key acts on the
 * row it was pressed on there.
 */
async function removeKey(item: ItemEnvelope): Promise<void> {
  if (!library.writable) return
  if (library.scope === 'publications') {
    askToUnpublish(item)
    return
  }

  const items = library.selectionKeys.includes(item.key) ? [...library.selectedItems] : [item]
  if (library.scope === 'trash' || items.every((entry) => entry.data.deleted)) {
    askToRemove(items)
    return
  }
  await runOnItem(() => library.trashItems(items.map((entry) => entry.key)))
}

/*
 * The same errands as words, for the item that is open.
 *
 * `moving` is the dialog: one list holding this library's collections and the
 * other libraries this account may write to, which is the keyboard's version
 * of dropping a row on a sidebar row.
 */
const moving = ref<ItemEnvelope[]>([])

const otherLibraries = computed(() =>
  library.libraries
    .filter((entry) => entry.id !== library.libraryId && entry.writable)
    .map((entry) => ({ id: entry.id, label: libraryLabel(entry) })),
)

const currentCollection = computed(() => {
  const node = library.selectedCollection
  return node ? { key: node.key, name: node.data.name } : null
})

async function submitDestination(destination: {
  library: number | null
  collection: string | null
  takeOut: boolean
}): Promise<void> {
  const items = moving.value
  if (!items.length) return
  const keys = items.map((item) => item.key)

  itemBusy.value = true
  itemError.value = null
  try {
    if (destination.library !== null) {
      await library.copyItems(keys, destination.library)
    } else {
      const from = currentCollection.value?.key
      const remove = destination.takeOut && from && from !== destination.collection ? [from] : []
      /* The library's own row is "no collection", which is a removal from
         every collection these items are in rather than an addition to any --
         the union of them, since one request states one set of removals and
         each item is only ever taken out of what it was actually in. */
      const add = destination.collection ? [destination.collection] : []
      const clearing = destination.collection
        ? []
        : [
            ...new Set(
              items.flatMap((item) => (item.data.collections as string[] | undefined) ?? []),
            ),
          ]
      await library.fileItems(keys, { add, remove: [...remove, ...clearing] })
    }
    moving.value = []
  } catch (thrown) {
    itemError.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    itemBusy.value = false
  }
}

/*
 * Picking out more than one row.
 *
 * Three ways in, because a mouse, a finger and a keyboard are three different
 * hands. `Ctrl`/`Cmd`-click adds a row and takes one away, `Shift`-click takes
 * everything between, and `Ctrl`/`Cmd`-A takes the whole page — the conventions
 * of every list anybody has used, and Zotero's own.
 *
 * None of those exist on a touch screen, and none of them can be reached by a
 * keyboard either: pressing a button fires a click with no modifier on it, so a
 * row that is only a button can only ever be selected on its own. That is what
 * **Select** is for. It draws a checkbox on every row, and a checkbox is a
 * control a finger can hit and a keyboard can reach with `Tab` and `Space`. It
 * is one control serving the two readers a modifier key leaves out, rather than
 * a touch affordance bolted onto a mouse interface.
 *
 * While it is on, pressing anywhere on a row toggles that row: in a mode whose
 * whole purpose is picking rows out, a tap that opened the detail pane instead
 * would be the mode failing to mean anything.
 */
const selecting = ref(false)

/* Turning the mode off leaves the selection alone -- it is how a reader gets
   back to reading after picking rows out, not an undo. */
function toggleSelecting(): void {
  selecting.value = !selecting.value
}

async function pressRow(item: ItemEnvelope, event: MouseEvent): Promise<void> {
  if (event.shiftKey) return void (await library.extendSelection(item))
  if (event.ctrlKey || event.metaKey || selecting.value) {
    return void (await library.toggleSelected(item))
  }
  await library.select(item)
}

/* On the list rather than on a row, so it works wherever the focus is inside
   it. Everything loaded, which is not everything there is -- the list pages, and
   an errand cannot act on rows that have not been fetched. */
async function selectAllKey(event: KeyboardEvent): Promise<void> {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return
  event.preventDefault()
  await library.selectAll()
}

const allSelected = computed(
  () => library.items.length > 0 && library.selection.length === library.items.length,
)

async function toggleAll(): Promise<void> {
  if (allSelected.value) {
    await library.clearSelection()
    return
  }
  await library.selectAll()
}

/*
 * Writing items out as a file, which the desktop client offers three ways:
 * Export Library…, Export Collection… and Export Items…. They are one errand
 * with three ways of saying which items — so this is one dialog, and the three
 * become the choice it offers rather than three controls to find.
 *
 * `null` while it is shut, and otherwise the choices in it, widest last. The
 * first is the one offered: rows picked out if there are any, because a
 * selection is a decision somebody has just made and an export that ignored it
 * would be answering a question nobody asked.
 */
interface ExportChoice {
  id: string
  /** What the radio says: "3 items selected", "Whales", "My Library". */
  label: string
  /** The rows to write out, or `null` for everything the scope holds. */
  keys: string[] | null
  /** What the file will be called. Settled here, since this is where the view
   *  has a name in the reader's own language. */
  name: string
  /** The library rather than the view: no collection, no search, no tags. */
  whole?: boolean
}

const exporting = ref<ExportChoice[] | null>(null)

/** Rows that would end up in the file: notes and attachments have no entry. */
function exportableItems(items: ItemEnvelope[]): ItemEnvelope[] {
  return items.filter((entry) => exportable(entry.data.itemType))
}

/* Offered only where it would produce something. The client greys its own menu
   item out when the view holds no items, for the same reason: an export of
   nothing is a file nobody wanted. */
const canExportView = computed(() => exportableItems(library.items).length > 0)

/** Whether the list is showing less than the whole library. */
const narrowed = computed(
  () =>
    library.collectionKey !== null ||
    library.scope !== 'top' ||
    library.search.trim() !== '' ||
    library.selectedTags.length > 0,
)

/** The choice for a set of rows, named as the client names one: by its title
 *  when it is a single row, and "Exported Items" when it is several. */
function rowsChoice(items: ItemEnvelope[]): ExportChoice {
  return {
    id: 'selection',
    label:
      items.length === 1
        ? titleOf(items[0])
        : t('{count} item selected | {count} items selected', items.length),
    keys: items.map((entry) => entry.key),
    /* Where the client offers a file picker to correct the name in, this has
       only what it guesses, and "Exported Items.bib" is no help sitting beside
       four other files of that name. */
    name: items.length === 1 ? titleOf(items[0]) : t('Exported Items'),
  }
}

/**
 * The wider things this list sits in: the view, and the library behind it.
 *
 * The view is offered only when it is narrower than the library — otherwise
 * the two are the same list under two names, which is a choice that is not one.
 * The heading names the view, because that is already what this view is called
 * on screen and a second answer is how the two end up disagreeing.
 */
function widerChoices(): ExportChoice[] {
  const name = library.library ? libraryLabel(library.library) : t('Library')
  const choices: ExportChoice[] = []
  if (narrowed.value) {
    choices.push({ id: 'view', label: heading.value, keys: null, name: heading.value })
  }
  choices.push({ id: 'library', label: name, keys: null, name, whole: true })
  return choices
}

/**
 * Export from the header, or from the pane that holds a selection.
 *
 * Both start from the rows picked out where there are any, and both offer the
 * way back out to the view and the library. The detail pane does not: its
 * button sits beside one item and means that item, and a radio offering the
 * whole library there would be a question nobody standing in front of a single
 * work is asking.
 */
function exportSelectionOrView(): void {
  const picked = exportableItems(library.selectedItems)
  exporting.value = [...(picked.length ? [rowsChoice(picked)] : []), ...widerChoices()]
}

/** Export one item, from the pane that is about it. */
function exportItem(item: ItemEnvelope): void {
  const wanted = exportableItems([item])
  if (!wanted.length) return
  exporting.value = [rowsChoice(wanted)]
}

function exportLink(format: string, id: string): string {
  const chosen = exporting.value?.find((entry) => entry.id === id) ?? exporting.value?.[0]
  return library.exportUrl(format, {
    keys: chosen?.keys ?? undefined,
    name: chosen?.name,
    whole: chosen?.whole,
  })
}

/** Whether everything picked out is already in the trash, which is what decides
 *  between throwing away and deleting for good. */
const selectionTrashed = computed(
  () =>
    library.scope === 'trash' ||
    (library.selectedItems.length > 0 &&
      library.selectedItems.every((entry) => entry.data.deleted === true)),
)

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
  <div
    class="library"
    :class="{ 'library--detail': showDetail }"
    :style="{ '--sidebar-width': `${sidebarWidth}px`, '--detail-width': `${detailWidth}px` }"
  >
    <aside class="library__sidebar">
      <!--
        The shape of the Zotero web library, because a person arriving here
        from it should not have to learn a second arrangement of the same
        library. "My Library" is the personal one, whatever the account is
        called: the row is the library, not its owner. Under it hang its
        collections, then My Publications, then the trash — and nothing else.
        The groups follow under a heading of their own.

        The views belong to a library rather than sitting above the list of
        them: "Trash" under a group is that group's trash, and one Trash over
        a list of libraries invited the reading that there is only the one.
      -->
      <nav class="library__libraries" :aria-label="t('Libraries')">
        <template v-for="entry in library.libraries" :key="entry.id">
          <!-- Zotero's own heading, and only where there is a group to head. -->
          <h2 v-if="entry.id === firstGroup" class="library__panel-title library__heading-group">
            {{ t('Group Libraries') }}
          </h2>

          <!--
            A drop here means one of two things, and which one is which library
            it is: this one takes the item out of the collection being shown,
            another one copies it over there.
          -->
          <div
            class="library__nav-row"
            :class="{ 'library__nav-row--over': lit(`library:${entry.id}`) }"
            :data-drop="`library:${entry.id}`"
          >
            <!-- The twisty says which library is open rather than opening one
                 of its own: what a library holds is what the panes below are
                 showing, and two libraries unfolded at once would be a tree of
                 things that are not on screen. -->
            <button
              class="library__twisty-button"
              type="button"
              :aria-label="entry.id === library.libraryId ? t('Collapse') : t('Expand')"
              :aria-expanded="entry.id === library.libraryId"
              @click="library.openLibrary(entry.id)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
                   :class="['library__chevron', { 'library__chevron--open': entry.id === library.libraryId }]">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </button>

            <button
              type="button"
              :class="['library__library', { 'library__library--current': showingWholeOf(entry.id) }]"
              :aria-current="showingWholeOf(entry.id) ? 'true' : undefined"
              @click="openLibrary(entry.id)"
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
            The desktop client's order, which is not quite the web library's:
            what has been read lately sits above the collections, and the
            views of the whole library sit below them. Every row shares the
            collections' twisty column, so a view and a collection line up.
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
                :class="['library__scope', { 'library__scope--current': library.scope === 'recentlyread' }]"
                :aria-current="library.scope === 'recentlyread' ? 'true' : undefined"
                @click="library.selectScope('recentlyread')"
              >
                <SidebarIcon name="recent" />
                <span class="library__label">{{ t('Recently Read') }}</span>
              </button>
            </div>

            <CollectionTree
              v-if="library.collections.length"
              :nodes="library.collections"
              :selected="library.collectionKey"
              :editable="library.writable"
              :carrying="carry.carrying.value !== null"
              :over="carry.target.value"
              @select="library.selectCollection($event)"
              @add="startNew($event)"
              @settings="startSettings($event)"
              @remove="startDelete($event)"
              @carry="carryCollection($event.node, $event.event)"
            />

            <!-- A group has no My Publications: publishing is something an
                 account does with its own library. Dropping a work here is how
                 the desktop client publishes one, and it opens the same
                 questions rather than publishing on the spot. -->
            <div
              v-if="entry.type === 'user'"
              class="library__scope-row"
              :class="{ 'library__scope-row--over': lit('publications:') }"
              data-drop="publications:"
            >
              <span class="library__twisty" aria-hidden="true"></span>
              <button
                type="button"
                :class="['library__scope', { 'library__scope--current': library.scope === 'publications' }]"
                :aria-current="library.scope === 'publications' ? 'true' : undefined"
                @click="library.selectScope('publications')"
              >
                <SidebarIcon name="publications" />
                <span class="library__label">{{ t('My Publications') }}</span>
              </button>
            </div>

            <div class="library__scope-row">
              <span class="library__twisty" aria-hidden="true"></span>
              <button
                type="button"
                :class="['library__scope', { 'library__scope--current': library.scope === 'duplicates' }]"
                :aria-current="library.scope === 'duplicates' ? 'true' : undefined"
                @click="library.selectScope('duplicates')"
              >
                <SidebarIcon name="duplicates" />
                <span class="library__label">{{ t('Duplicate Items') }}</span>
              </button>
            </div>

            <div class="library__scope-row">
              <span class="library__twisty" aria-hidden="true"></span>
              <button
                type="button"
                :class="['library__scope', { 'library__scope--current': library.scope === 'unfiled' }]"
                :aria-current="library.scope === 'unfiled' ? 'true' : undefined"
                @click="library.selectScope('unfiled')"
              >
                <SidebarIcon name="unfiled" />
                <span class="library__label">{{ t('Unfiled Items') }}</span>
              </button>
            </div>

            <div
              class="library__scope-row"
              :class="{ 'library__scope-row--over': lit('trash:') }"
              data-drop="trash:"
            >
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
          </div>

          <template v-if="entry.id === library.libraryId">
            <!-- Below the list rather than over it, so the tree does not move
                 down while the question is being read. -->
            <p v-if="pending?.kind === 'delete'" class="block collections__confirm" role="alert">
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

    <PaneSplitter
      class="library__grip library__grip--sidebar"
      :width="sidebarWidth"
      :min="SIDEBAR.min"
      :max="SIDEBAR.max"
      :preferred="SIDEBAR.preferred"
      :label="t('Sidebar width')"
      @update:width="resizeSidebar"
    />

    <section class="library__list">
      <header class="library__header">
        <h1 class="library__heading">{{ heading }}</h1>

        <!--
          One row of tools at the end of the header, the search last.
          Everything here acts on the list below, and a control that acts on
          the list belongs beside the one that narrows it rather than strung
          out across the width of the screen.

          Glyphs rather than words, and so each carries its name twice: as
          `aria-label`, which is what a screen reader announces, and as
          `title`, which is what a pointer reveals. A control with neither is a
          rebus.
        -->
        <div class="library__tools toolbar">
          <!--
            Checkboxes on demand: the way in for a finger, which has no
            modifier keys, and for a keyboard, which cannot press a row with
            one held. A mouse needs neither and is not made to use it —
            `Ctrl`-click and `Shift`-click work whether this is on or off.
          -->
          <button
            v-if="library.items.length"
            class="icon-button library__tool"
            :class="{ 'icon-button--on': selecting }"
            type="button"
            :aria-pressed="selecting"
            :aria-label="selecting ? t('Done selecting') : t('Select')"
            :title="selecting ? t('Done selecting') : t('Select')"
            @click="toggleSelecting()"
          >
            <SidebarIcon name="select" :size="18" />
          </button>

          <!--
            What the client calls Export Library… and Export Collection…: this
            list, written out as a file. Beside Select rather than inside it,
            because it is about what is on screen and not about what was
            picked out — the panes on the right export a selection.
          -->
          <button
            v-if="canExportView"
            class="icon-button library__tool"
            type="button"
            :aria-label="t('Export…')"
            :title="t('Export…')"
            @click="exportSelectionOrView()"
          >
            <SidebarIcon name="export" :size="18" />
          </button>

          <!-- Emptying the trash is the one errand that reaches items nobody
               picked out: the trash is a list of things already thrown away.
               It asks before it goes ahead, which is what makes a glyph enough
               for something this final.

               The same glyph the panes draw for deleting one item for good,
               because it is the same act on more of them — the bin with a
               cross through it, never the plain bin, which everywhere here
               means the trash an item can still come back out of. -->
          <button
            v-if="
              library.scope === 'trash' &&
              library.writable &&
              library.permission !== 'add' &&
              library.items.length
            "
            class="icon-button icon-button--danger library__tool"
            type="button"
            :aria-label="t('Empty the trash')"
            :title="t('Empty the trash')"
            @click="askToEmpty()"
          >
            <SidebarIcon name="deleteforever" :size="18" />
          </button>

          <!--
            The list of what has been published, and the page it is published
            on. The wizard promises the work "will be shown on your profile
            page"; this is where somebody standing in front of that list can go
            and read the page as everybody else does.
          -->
          <RouterLink
            v-if="library.scope === 'publications' && auth.user"
            class="icon-button library__tool"
            :aria-label="t('See your public page')"
            :title="t('See your public page')"
            :to="{ name: 'profile', params: { username: auth.user.username } }"
          >
            <SidebarIcon name="account" :size="18" />
          </RouterLink>

          <!--
            Closed, the search is one more glyph in the row; open, it is the
            field it always was. It opens when it is pressed and closes again
            when it is left empty, so the width it takes is the width it is
            using — and it stays open while it holds a term, because a list
            filtered by a word nothing on screen shows is a list that looks
            wrong for no reason.
          -->
          <div class="library__search" :class="{ 'library__search--open': searching }">
            <button
              v-if="!searching"
              class="icon-button library__tool"
              type="button"
              :aria-label="t('Search this library')"
              :title="t('Search this library')"
              @click="openSearch"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
                <path d="M10.75 4.75a6 6 0 100 12 6 6 0 000-12z M15.25 15.25l4 4" />
              </svg>
            </button>
            <template v-else>
              <svg class="library__search-icon" width="16" height="16" viewBox="0 0 24 24"
                   fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
                   aria-hidden="true">
                <path d="M10.75 4.75a6 6 0 100 12 6 6 0 000-12z M15.25 15.25l4 4" />
              </svg>
              <input
                ref="searchField"
                v-model="searchText"
                class="library__search-field"
                type="search"
                :placeholder="t('Search')"
                :aria-label="t('Search this library')"
                @blur="closeSearchIfEmpty"
                @keydown.esc.stop="escapeSearch"
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
            </template>
          </div>
        </div>
      </header>

      <p v-if="library.failure" class="library__state library__state--error" role="alert">
        {{ library.failure }}
      </p>

      <p v-if="itemError" class="library__state library__state--error" role="alert">
        {{ itemError }}
      </p>

      <!--
        Asked in the list, above the rows it is about. Deleting out of the
        trash is the only thing in this interface that cannot be undone, so it
        is the only one that asks.
      -->
      <p
        v-if="removing.length || emptying || unpublishing"
        class="block collections__confirm"
        role="alert"
      >
        <span v-if="emptying">
          {{ t('Delete everything in the trash?') }} {{ t('This cannot be undone.') }}
        </span>
        <!-- Named while there is one, counted once there are several: five
             titles in a sentence is not a sentence anybody reads. -->
        <span v-else-if="removing.length === 1">
          {{ t('Delete “{name}” for good?', { name: titleOf(removing[0]) }) }}
          {{ t('This cannot be undone.') }}
        </span>
        <span v-else-if="removing.length">
          {{ t('Delete {count} items for good?', { count: removing.length }) }}
          {{ t('This cannot be undone.') }}
        </span>
        <!-- Nothing is deleted here, and the sentence says so: the work stays
             in the library, and what goes is its place in the published list
             and that of the notes and files published with it. -->
        <span v-else-if="unpublishing">
          {{ t('Remove “{name}” from My Publications?', { name: titleOf(unpublishing) }) }}
          {{ t('It stays in your library, with its notes and files.') }}
        </span>
        <span class="collections__actions">
          <AppButton variant="text" :disabled="itemBusy" @click="cancelRemoval">
            {{ t('Cancel') }}
          </AppButton>
          <AppButton
            v-if="unpublishing"
            :loading="itemBusy"
            @click="unpublishing && unpublishItem(unpublishing)"
          >
            {{ t('Remove') }}
          </AppButton>
          <AppButton
            v-else
            :loading="itemBusy"
            @click="emptying ? emptyTrash() : deleteItems(removing)"
          >
            {{ t('Delete') }}
          </AppButton>
        </span>
      </p>

      <!--
        A list of buttons rather than a table of rows. The columns are how the
        items are laid out, not what they are: a `role="row"` that is a button
        promises cell-by-cell navigation that nothing here implements, and the
        header cells are sort controls rather than headers.
      -->
      <div v-else class="library__table">
        <div class="library__line table-head">
          <!-- One box for the whole page, and only while Select is on: a column
               of checkboxes over a list nobody is picking from is a column of
               questions nobody asked. It sits beside the grid rather than in
               it, so that the columns underneath line up with the headings. -->
          <span v-if="selecting" class="library__cell library__cell--check">
            <input
              type="checkbox"
              :checked="allSelected"
              :aria-label="t('Select everything shown')"
              @change="toggleAll()"
            />
          </span>
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

        <ul
          v-else
          class="library__items table-rows"
          :aria-label="t('Items in {name}', { name: heading })"
          @keydown.a="selectAllKey"
          @keydown.esc="library.clearSelection()"
        >
          <li v-for="item in library.items" :key="item.key" class="library__line">
            <!-- The checkbox is a sibling of the row rather than inside it: a
                 checkbox within a button is neither, and a reader tabbing
                 through would find one control where there are two. -->
            <span v-if="selecting" class="library__cell library__cell--check">
              <input
                type="checkbox"
                :checked="library.selection.includes(item.key)"
                :aria-label="t('Select “{name}”', { name: titleOf(item) })"
                @change="library.toggleSelected(item)"
              />
            </span>

            <!--
              Carried only where the library can be written to: a drag that can
              only ever be refused is a promise the interface should not make.
              `Delete` does what dropping on the trash does, so the keyboard is
              not the poor relation.
            -->
            <button
              type="button"
              :class="[
                'library__row',
                {
                  'library__row--selected row--current': library.selection.includes(item.key),
                  'library__row--carried': carriedKeys.has(item.key),
                },
              ]"
              :aria-pressed="library.selection.includes(item.key)"
              @click="pressRow(item, $event)"
              @pointerdown="carryItem(item, $event)"
              @keydown.delete.prevent="removeKey(item)"
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

    <!-- Only while there is a pane to size: a grip in the gutter of a column
         that is not there would be a divide between the list and nothing. -->
    <PaneSplitter
      v-if="showDetail"
      class="library__grip library__grip--detail"
      trailing
      :width="detailWidth"
      :min="DETAIL.min"
      :max="DETAIL.max"
      :preferred="DETAIL.preferred"
      :label="t('Detail width')"
      @update:width="resizeDetail"
    />

    <aside v-if="showDetail && library.libraryId !== null" class="pane library__detail">
      <ItemDetail
        v-if="library.selected"
        :item="library.selected"
        :children="library.children"
        :library-id="library.libraryId"
        :file-url="library.fileUrl"
        :writable="library.selected ? library.changeable(library.selected) : false"
        :removable="library.selected ? library.removable(library.selected) : false"
        :publishable="library.writable && library.library?.type === 'user'"
        :in-publications-view="library.scope === 'publications'"
        @open="library.select($event)"
        @close="library.select(null)"
        @move="moving = [library.selected]"
        @trash="runOnItem(() => library.trashItems([library.selected!.key]))"
        @restore="runOnItem(() => library.trashItems([library.selected!.key], false))"
        @remove="askToRemove([library.selected!])"
        @publish="startPublishing(library.selected!)"
        @unpublish="askToUnpublish(library.selected!)"
        @rights="editingRights = library.selected"
        @export="exportItem(library.selected!)"
      />
      <!-- More than one row picked out: a count and the errands, because what
           several items have in common is what can be done to them rather than
           what their fields say. -->
      <ItemSelection
        v-else
        :count="library.selection.length"
        :writable="library.selectionChangeable"
        :removable="library.selectionRemovable"
        :trashed="selectionTrashed"
        :exportable="exportableItems(library.selectedItems).length > 0"
        @move="moving = [...library.selectedItems]"
        @trash="runOnItem(() => library.trashItems(library.selectionKeys))"
        @restore="runOnItem(() => library.trashItems(library.selectionKeys, false))"
        @remove="askToRemove([...library.selectedItems])"
        @export="exportSelectionOrView()"
        @close="library.clearSelection()"
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

    <!-- Renaming, moving and deleting one collection, which are one dialog
         because they are one thought: this collection's settings. -->
    <CollectionSettingsDialog
      v-if="editing"
      :name="editing.data.name"
      :parent-key="editing.data.parentCollection || null"
      :places="places"
      :busy="busy"
      :error="collectionError"
      @submit="submitSettings"
      @remove="startDelete(editing)"
      @share="startSharing(editing)"
      @cancel="cancel"
    />

    <!-- The links that show one collection to whoever holds them. Not sync and
         not a permission: a page, at an address that can be sent to somebody
         with no account here. -->
    <ShareDialog
      v-if="sharing"
      :collection-name="sharing.data.name"
      :shares="shares.shares"
      :issued="shares.issued"
      :busy="shares.busy"
      :error="shares.error"
      @create="createShare"
      @revoke="revokeShare"
      @cancel="stopSharing"
    />

    <!--
      What is being carried, drawn under the pointer. The browser used to do
      this from the element itself; a carry made of pointer events has to say
      what it holds, or a finger is dragging nothing anybody can see.
    -->
    <div
      v-if="carry.carrying.value"
      class="library__cargo"
      :style="{ left: `${carry.position.value.x}px`, top: `${carry.position.value.y}px` }"
      aria-hidden="true"
    >
      {{ carry.carrying.value.label }}
    </div>

    <!-- Dropping a row on a sidebar row, said in words: the collections of
         this library and the other libraries it could be copied to. -->
    <ItemDestinationDialog
      v-if="moving.length"
      :title="
        moving.length === 1 ? titleOf(moving[0]) : t('{count} item | {count} items', moving.length)
      "
      :count="moving.length"
      :places="places"
      :libraries="otherLibraries"
      :current-collection="currentCollection"
      :busy="itemBusy"
      :error="itemError"
      @submit="submitDestination"
      @cancel="moving = []"
    />

    <!-- Everything the desktop client asks before it publishes something,
         asked in the same order. Mounted only while it is open, so it always
         starts on its first page. -->
    <PublicationsDialog
      v-if="publishing"
      :title="titleOf(publishing)"
      :has-files="publishHasFiles"
      :has-notes="publishHasNotes"
      :has-rights="publishHasRights"
      :busy="itemBusy"
      :error="itemError"
      @submit="submitPublication"
      @cancel="publishing = null"
    />

    <!-- The licence of a published work, and the Rights field of anything
         else: one dialog, because they are one field. -->
    <RightsDialog
      v-if="editingRights"
      :title="titleOf(editingRights)"
      :rights="(editingRights.data.rights as string) ?? ''"
      :busy="itemBusy"
      :error="itemError"
      @submit="submitRights"
      @cancel="editingRights = null"
    />

    <!-- Which format the file is written in — the client's export options
         dialog, with the one question altero's four formats leave it. -->
    <ExportDialog
      v-if="exporting"
      :scopes="exporting"
      :link="exportLink"
      @close="exporting = null"
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
@import '@/styles/surfaces.css';

/*
 * The sidebar's width is whatever the reader dragged it to, kept in
 * `--sidebar-width` so that the grid and the grip sitting in the gutter read it
 * from one place. `position: relative` is what the grip positions against.
 */
.library {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  gap: var(--md-spacing-4);
  align-items: start;
  position: relative;
}

/* The item takes what it was given and the list takes the rest. An abstract is
   prose, often several hundred words of it, and in a column narrow enough to be
   a sidebar it is a ribbon of text nobody reads -- so the pane starts wide, and
   which of the two deserves the room after that is the reader's to say. Below
   60rem the whole thing stacks anyway. */
.library--detail {
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr) var(--detail-width);
}

/* Both grips sit in the middle of the gap the grid already leaves, so the
   panes stay exactly as far apart as they were. */
.library__grip--sidebar {
  left: calc(var(--sidebar-width) + var(--md-spacing-4) / 2);
}

.library__grip--detail {
  right: calc(var(--detail-width) + var(--md-spacing-4) / 2);
  transform: translateX(50%);
}

/* Stacked, so there is no vertical divide left to move. */
@media (max-width: 60rem) {
  .library__grip {
    display: none;
  }
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
 * indent, and adding a level's worth on top of it pushes the whole list into
 * the middle of the column. The column can be widened now, but a tree indents
 * per level and the deepest branch is the one that has to survive the
 * narrowest setting.
 *
 * The rule down the left is the thread back up to the library they act on, and
 * it is the same hairline the tag panel's heading uses.
 */
.library__scopes--nested {
  margin-left: 0.3rem;
  padding-left: 0.35rem;
  border-left: 1px solid var(--md-sys-color-outline-variant);
}

/*
 * The heading over the groups. It is the tag panel's heading, because it is
 * the same kind of thing: a word over a list saying what the list is.
 */
.library__heading-group {
  margin-top: var(--md-spacing-3);
}

/* The twisty on a library row, in the same column the collections use, so a
   library and a collection line up down the left. */
.library__twisty-button {
  display: grid;
  flex: none;
  place-items: center;
  width: 1.5rem;
  height: 1.5rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.library__chevron {
  transition: transform 120ms ease;
}

.library__chevron--open {
  transform: rotate(90deg);
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

/* After the two rules above rather than beside the other coarse-pointer block,
   because a media query adds no specificity: the plain `width` would win on
   whichever of them came last. The tree's twisty grows for a fingertip, so the
   column the views hold open has to grow with it or the collections stand a
   finger's width to the right of every other row. */
@media (pointer: coarse) {
  .library__twisty-button,
  .library__twisty {
    width: 2.25rem;
  }

  .library__twisty-button {
    height: 2.25rem;
  }
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
  background: var(--md-sys-state-hover-surface);
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

/* An outline rather than a fill on the row a drag is over, so it does not
   look like the row that is selected. */
.library__nav-row--over,
.library__scope-row--over {
  border-radius: var(--md-sys-shape-corner-small);
  outline: 2px solid var(--md-sys-color-primary);
  outline-offset: -1px;
}

/* The row being carried, dimmed so that the pointer is visibly taking
   something out of the list rather than duplicating it in place. */
.library__row--carried {
  opacity: 0.5;
}

/*
 * What is being carried, following the pointer.
 *
 * Offset down and to the right so that a fingertip is not covering the thing
 * it is holding, and `pointer-events: none` so it never becomes what is under
 * the pointer -- which is how the drop target is found.
 */
.library__cargo {
  position: fixed;
  z-index: 10;
  max-width: 16rem;
  margin: 0.75rem 0 0 0.75rem;
  padding: 0.3rem 0.7rem;
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  box-shadow: 0 2px 10px rgb(0 0 0 / 25%);
  font-size: var(--md-sys-typescale-body-medium-size);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
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
  /* 24 CSS pixels square, the smallest target WCAG 2.2 accepts (2.5.8). The
     glyph inside it stays the size it was. */
  width: 1.5rem;
  height: 1.5rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.library__action:hover {
  background: var(--md-sys-state-hover-surface);
  color: var(--md-sys-color-on-surface);
}

/* A pointer that cannot hover cannot reveal anything, and a phone showing the
   sidebar is showing all of it. */
@media (hover: none) {
  .library__actions {
    opacity: 1;
  }

  /* Same reason: the pencil on a tag is dimmed until the pointer arrives, and
     a finger has no way of arriving without pressing. */
  .library__tag-action {
    opacity: 1;
  }
}

/*
 * What a fingertip needs, which is roughly a centimetre in each direction.
 * The rows and the controls grow; the type and the icons in them do not.
 */
@media (pointer: coarse) {
  .library__action,
  .library__search-clear {
    width: 2.25rem;
    height: 2.25rem;
  }

  /* The glyphs over the list are the smallest targets on this screen, and the
     one a finger reaches for most. The closed search grows with them, since it
     is one of them until it is pressed. */
  .library__tool,
  .library__search {
    width: 2.5rem;
    height: 2.5rem;
  }

  .library__search--open {
    height: auto;
  }

  .library__tag-action {
    width: 1.6rem;
    height: 1.6rem;
  }

  .library__library,
  .library__scope {
    padding: 0.6rem 0.5rem;
  }

  .library__tag {
    padding: 0.4rem 0.7rem;
  }

  .library__row:not(.library__row--head) {
    padding: var(--md-spacing-4);
  }

  .library__more {
    padding: 0.55rem 1rem;
  }
}

/* A press held on a row is a carry, so the browser's own answer to a held
   press must not land on top of it. */
.library__row {
  user-select: none;
  -webkit-touch-callout: none;
}

.collections__confirm {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
  margin: 0;
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
  background: var(--md-sys-state-hover-surface);
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
  width: 1.5rem;
  height: 1.5rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  opacity: 0.45;
  transition: opacity 120ms ease;
  cursor: pointer;
}

.library__tag:hover .library__tag-action {
  opacity: 1;
}

/* Split from the rule above rather than listed with it: `:focus-visible`
   arrived in Safari 15.4, and a browser that does not know a selector throws
   away the whole rule it appears in — hover included. */
.library__tag-action:focus-visible {
  opacity: 1;
}

.library__tag-action:hover {
  background: var(--md-sys-state-hover-surface);
  color: var(--md-sys-color-on-surface);
  opacity: 1;
}

.library__tag .library__label {
  overflow: visible;
  word-break: break-word;
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
  flex-wrap: wrap;
  align-items: center;
  gap: var(--md-spacing-4);
}

.library__heading {
  /* Takes what is left and gives it up first: a collection with a long name
     shortens its heading rather than pushing the tools off the end, and when
     even that is not enough the tools wrap to a line of their own. */
  flex: 1 1 8rem;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: var(--md-sys-typescale-title-large-size, 1.35rem);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Everything that acts on the list, gathered at the end of the header. */
.library__tools {
  display: flex;
  flex: 0 1 auto;
  align-items: center;
  gap: var(--md-spacing-1);
  min-width: 0;
  margin-left: auto;
}

.library__search {
  display: flex;
  flex: none;
  align-items: center;
  gap: var(--md-spacing-2);
  /* Closed, it is exactly one tool wide, and the border and background are the
     tool's own -- which is none, so that a row of glyphs reads as a row. */
  width: 2rem;
  border: 1px solid transparent;
  border-radius: var(--md-sys-shape-corner-medium);
  transition: width 180ms ease;
}

.library__search--open {
  /* Wide enough for a phrase, and never more than a screenful: on a phone the
     header is the width of the window, and a field that took all of it would
     leave the heading nowhere to go. */
  width: min(18rem, 60vw);
  padding: 0.3rem 0.6rem;
  /* A control's own border has to be discernible: `outline`, not the divider. */
  border-color: var(--md-sys-color-outline);
  background: var(--md-sys-color-surface);
}

.library__search:focus-within {
  border-color: var(--md-sys-color-primary);
}

/* The width is a nicety; somebody who has asked for less movement gets the
   field at once instead. */
@media (prefers-reduced-motion: reduce) {
  .library__search {
    transition: none;
  }
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
  width: 1.5rem;
  height: 1.5rem;
  padding: 0;
  border: none;
  border-radius: var(--md-sys-shape-corner-full);
  background: none;
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
}

.library__search-clear:hover {
  background: var(--md-sys-state-hover-surface);
  color: var(--md-sys-color-on-surface);
}

/* A table rather than a card: what bounds it is the filled strip its headings
   sit in, the rule under that, and the hairlines between its rows. A fill
   behind the rows themselves would tint the thing being read, and an outline
   around the whole is the box this interface stopped drawing -- see
   docs/design.md. */
.library__table {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.library__items {
  margin: 0;
  padding: 0;
  list-style: none;
}

/* A row and the box that picks it out, side by side. The box is outside the
   grid the cells live in, and the same width on the heading line, so turning
   Select on shifts the whole table across rather than pulling the columns out
   of line with their headings. */
.library__line {
  display: flex;
  align-items: stretch;
}

.library__line > .library__row {
  flex: 1;
  min-width: 0;
}

.library__cell--check {
  display: grid;
  flex: none;
  place-items: center;
  width: 2.5rem;
}

/* The box is the target -- the cell around it takes no click -- so it carries
   the 24 CSS pixels WCAG 2.2 asks of one (2.5.8), and more where the pointer
   is a fingertip. */
.library__cell--check input {
  width: 1.5rem;
  height: 1.5rem;
  accent-color: var(--md-sys-color-primary);
}

@media (pointer: coarse) {
  .library__cell--check {
    width: 3rem;
  }

  .library__cell--check input {
    width: 1.75rem;
    height: 1.75rem;
  }
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
  /* The hairline belongs to the line rather than to the row: a row is the last
     child of its line whether or not a checkbox is beside it, so a rule drawn
     here and taken off `:last-child` comes off every row. */
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.library__row--head {
  padding: 0;
  cursor: default;
}

.library__row:hover:not(.library__row--head) {
  background: var(--md-sys-state-hover-surface);
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

/* Dates line up under one another rather than wandering by digit. */
.library__row > .library__cell:last-child {
  font-variant-numeric: tabular-nums;
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
  /* The pill is worn by a button and by one link -- the public page -- and a
     link brings an underline and a colour of its own that would make the two
     read as different kinds of control. */
  text-decoration: none;
}

.library__detail {
  position: sticky;
  top: var(--md-spacing-4);
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
