<script setup lang="ts">
/**
 * Taking a library out of this server, and putting one back.
 *
 * The archive is the same one `altero library export` writes: every object at
 * the version clients remember, the deletion log, and the attachment bytes. It
 * is a move or a backup, not an export for another application — BibTeX, RIS
 * and the rest are what an item list is for.
 *
 * This is the one place in the interface that writes to a library, and it does
 * so wholesale, so what the screen offers follows the role the *server*
 * resolved: administrators of a group may take a copy, only its owner may
 * restore over it, and both are refused there as well as hidden here.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { libraryLabel } from '@/librarylabel'
import type { LibrarySummary } from '@/stores/library'
import { message, usePanel } from './panel'

const { t } = useI18n()

const { busy, failure, attempt } = usePanel()

/** What a group says about this account, which is what decides the controls. */
interface GroupEntry {
  id: number
  role: string
  owner: boolean
}

/** What a restore did, as the server reported it. */
interface Restored {
  library: { name: string; version: number }
  counts: Record<string, number>
  source: { type: string; ownerId: number | null; name: string }
}

const libraries = ref<LibrarySummary[]>([])
const groups = ref<GroupEntry[]>([])

const target = ref<number | null>(null)
const file = ref<File | null>(null)
const replace = ref(false)
const password = ref('')

/** Kept on screen after a restore, until the section is left. */
const restored = ref<Restored | null>(null)
const picker = ref<HTMLInputElement | null>(null)

function group(library: LibrarySummary): GroupEntry | undefined {
  return groups.value.find((entry) => entry.id === library.id)
}

/** A personal library is its owner's; a group's copy is its administrators'. */
function mayExport(library: LibrarySummary): boolean {
  return library.type === 'user' || group(library)?.role === 'admin'
}

/* Restoring ends the library as everyone else knew it, which is what deleting
   a group does, so it is held to the same person. */
function mayImport(library: LibrarySummary): boolean {
  return library.type === 'user' || group(library)?.owner === true
}

const exportable = computed(() => libraries.value.filter(mayExport))
const importable = computed(() => libraries.value.filter(mayImport))

const chosen = computed(() => libraries.value.find((entry) => entry.id === target.value) ?? null)

/* The same words the library page uses, from the same function: this page
   listed the account holder's own name while the sidebar said "My Library",
   which is two names for one library on two screens of one application. */
const name = libraryLabel

const targetName = computed(() => (chosen.value ? name(chosen.value) : ''))

/**
 * Which library the archive was made from, named as well as it can be.
 *
 * Not `libraryLabel`, deliberately: this names a library somewhere else — on
 * another server, belonging to somebody else — as its manifest recorded it.
 * Calling that "My Library" would claim it was this account's own.
 */
function sourceName(done: Restored): string {
  const source = done.source
  if (!source) return ''
  return source.name || `${source.type}/${source.ownerId}`
}

/** Where the browser fetches the archive from. A plain link, so it streams to
    disk rather than through memory: an archive is as large as the library. */
function archiveUrl(library: LibrarySummary): string {
  return `/web/libraries/${library.id}/archive`
}

onMounted(async () => {
  try {
    libraries.value = await request<LibrarySummary[]>('/web/libraries')
    groups.value = (await request<{ groups: GroupEntry[] }>('/web/groups')).groups
    target.value = importable.value[0]?.id ?? null
  } catch (thrown) {
    failure.value = message(thrown)
  }
})

function chooseFile(event: Event): void {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

const restore = () =>
  attempt(async () => {
    const library = chosen.value
    if (!file.value || !library) {
      // Not reachable through the button, which is disabled without both.
      throw new Error(t('Choose a library and an archive first.'))
    }
    const form = new FormData()
    form.append('archive', file.value)
    form.append('currentPassword', password.value)
    form.append('replace', String(replace.value))

    restored.value = await request<Restored>(archiveUrl(library), { method: 'POST', body: form })

    // Cleared on the way out, the file included: leaving a chosen archive and
    // a ticked "replace" in the form invites a second restore by one click.
    password.value = ''
    replace.value = false
    file.value = null
    if (picker.value) {
      picker.value.value = ''
    }
    libraries.value = await request<LibrarySummary[]>('/web/libraries')
  }, t('The library was restored.'))
</script>

<template>
  <section class="card">
    <h2 class="card__title">{{ t('Export a library') }}</h2>
    <p class="settings__detail">
      {{
        t('An archive holds everything in the library — items, collections, tags, saved searches and attached files — at the versions your Zotero clients know. Keep it as a backup, or restore it on another altero server.')
      }}
    </p>

    <ul v-if="exportable.length" class="settings__list">
      <li v-for="library in exportable" :key="library.id">
        <div>
          <p class="settings__entry">{{ name(library) }}</p>
          <p class="settings__detail">
            {{ t('Version {version}', { version: library.version }) }}
          </p>
        </div>
        <!-- A link rather than a fetch: the browser streams it to disk and
             shows its own progress, and an archive can be gigabytes. -->
        <a class="settings__download" :href="archiveUrl(library)" download>
          {{ t('Download') }}
        </a>
      </li>
    </ul>
    <p v-else class="settings__detail">{{ t('No library here is yours to export.') }}</p>
  </section>

  <section class="card">
    <h2 class="card__title">{{ t('Restore a library') }}</h2>
    <p class="settings__detail">
      {{
        t('Reads an archive back into a library of yours. The library is restored to the state the archive holds, versions included, so a Zotero client that synced with it carries on where it left off.')
      }}
    </p>

    <template v-if="importable.length">
      <label class="settings__field">
        <span class="settings__field-label">{{ t('Restore into') }}</span>
        <select v-model="target" class="settings__select">
          <option v-for="library in importable" :key="library.id" :value="library.id">
            {{ name(library) }}
          </option>
        </select>
      </label>

      <label class="settings__field">
        <span class="settings__field-label">{{ t('Archive') }}</span>
        <input ref="picker" class="settings__file" type="file" accept=".zip,application/zip"
               @change="chooseFile" />
      </label>

      <label class="settings__check">
        <input v-model="replace" type="checkbox" />
        <span>{{ t('Replace what this library already holds') }}</span>
      </label>

      <p v-if="replace" class="card__warning" role="status">
        {{
          t('Everything in {name} is deleted first, files included, and there is no trash around it.', { name: targetName })
        }}
      </p>
      <p v-else class="settings__detail">
        {{ t('Without this, a library that already holds anything is left alone rather than merged into.') }}
      </p>

      <AppTextField
        v-model="password"
        :label="t('Current password')"
        type="password"
        autocomplete="current-password"
      />

      <AppButton :loading="busy" :disabled="!file || target === null" @click="restore">
        {{ t('Restore') }}
      </AppButton>

      <!-- Read defensively: the restore has already happened by the time this
           is drawn, and a report that cannot be rendered would replace the
           news that it worked with a blank screen. -->
      <div v-if="restored" class="card__inset settings__restored">
        <p class="settings__detail">
          {{
            t('{items} items, {collections} collections and {files} files, from an archive of {source}.', {
              items: restored.counts?.items ?? 0,
              collections: restored.counts?.collections ?? 0,
              files: restored.counts?.files ?? 0,
              source: sourceName(restored),
            })
          }}
        </p>
        <p class="settings__detail">
          {{ t('The library is now at version {version}.', { version: restored.library?.version ?? 0 }) }}
        </p>
      </div>
    </template>
    <p v-else class="settings__detail">{{ t('No library here is yours to restore into.') }}</p>
  </section>
</template>

<style scoped>
@import '@/styles/settings.css';

/* A link that does what the buttons beside it do, so it is dressed as one --
   an anchor rather than a button because it is a download, and only an anchor
   hands one to the browser. */
.settings__download {
  padding: 0.35rem 0.9rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-full);
  color: var(--md-sys-color-primary);
  font-size: var(--md-sys-typescale-label-large-size);
  text-decoration: none;
  white-space: nowrap;
}

.settings__download:hover {
  background: var(--md-sys-state-hover-surface);
}

.settings__file {
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.settings__restored {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}
</style>
