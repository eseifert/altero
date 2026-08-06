<script setup lang="ts">
/**
 * Copying a personal library in from zotero.org.
 *
 * The screen has to say three things before it asks for anything, because all
 * three are surprising: that zotero.org has no password login and this takes a
 * key you make there; that the copy replaces what is here rather than merging
 * into it; and that the desktop client will want to reset itself afterwards.
 * A migration nobody warned about is one somebody starts over their only copy.
 *
 * It takes minutes rather than moments, so the request only starts the work.
 * What follows is polled: the stage, the count within it, and at the end what
 * came across and what did not. Polling stops when it finishes, when the
 * section is left, and when the page is hidden — a tab left open behind
 * another for an hour should not be asking every two seconds.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { message, usePanel } from './panel'

const { t } = useI18n()
const { failure, notice } = usePanel()

/** What the server reports about a migration, running or finished. */
interface Status {
  running: boolean
  stage: string
  done: number
  total: number | null
  detail: string
  error: string | null
  summary?: {
    userID: number
    username: string
    libraryVersion: number
    items: number
    collections: number
    searches: number
    tags: number
    files: number
    filesMissing: string[]
    skipped: { key: string; reason: string }[]
    unavailable: string[]
    rewritten: number
    complete: boolean
  }
}

const apiKey = ref('')
const password = ref('')
const replace = ref(false)
const starting = ref(false)
const status = ref<Status | null>(null)

let timer: ReturnType<typeof setTimeout> | undefined

const running = computed(() => status.value?.running === true)
const summary = computed(() => status.value?.summary ?? null)

/* The stages are named by the server in English; the interface says them in
   the reader's own language, and falls back to the raw name for one it has not
   been taught — a new stage should read oddly, not blankly. */
const STAGES: Record<string, () => string> = {
  connecting: () => t('Connecting to zotero.org…'),
  items: () => t('Reading items…'),
  collections: () => t('Reading collections…'),
  searches: () => t('Reading saved searches…'),
  tags: () => t('Reading tags…'),
  settings: () => t('Reading settings…'),
  'full text': () => t('Reading full text…'),
  deleted: () => t('Reading the deletion log…'),
  files: () => t('Downloading attachments…'),
  restoring: () => t('Writing it into your library…'),
  done: () => t('Finished.'),
  failed: () => t('Stopped.'),
}

const stageLabel = computed(() => {
  const current = status.value
  if (!current) return ''
  const named = STAGES[current.stage]
  return named ? named() : current.stage
})

/** "412" or "412/900", and nothing at all before there is anything to count. */
const counted = computed(() => {
  const current = status.value
  if (!current || !current.done) return ''
  return current.total ? `${current.done} / ${current.total}` : String(current.done)
})

async function poll(): Promise<void> {
  try {
    status.value = await request<Status | null>('/web/migrate/zotero')
  } catch (thrown) {
    failure.value = message(thrown)
    return
  }
  if (status.value?.running && document.visibilityState !== 'hidden') {
    timer = setTimeout(poll, 2000)
  }
}

/* A tab brought back to the front catches up at once rather than waiting out
   the interval it stopped polling on. */
function resume(): void {
  if (document.visibilityState === 'visible' && status.value?.running) {
    clearTimeout(timer)
    void poll()
  }
}

onMounted(() => {
  void poll()
  document.addEventListener('visibilitychange', resume)
})

onUnmounted(() => {
  clearTimeout(timer)
  document.removeEventListener('visibilitychange', resume)
})

async function begin(): Promise<void> {
  starting.value = true
  notice.value = null
  failure.value = null
  try {
    status.value = await request<Status>('/web/migrate/zotero', {
      method: 'POST',
      body: {
        apiKey: apiKey.value.trim(),
        currentPassword: password.value,
        replace: replace.value,
      },
    })
    // Neither is needed again, and both are worth keeping for no longer than
    // the request that used them.
    apiKey.value = ''
    password.value = ''
    void poll()
  } catch (thrown) {
    failure.value = message(thrown)
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <section class="settings__card">
    <h2>{{ t('Copy your library from zotero.org') }}</h2>
    <p class="settings__detail">
      {{
        t('Reads your personal library from zotero.org — items, collections, tags, saved searches, notes and attached files — and puts it here, keeping the versions your Zotero clients know.')
      }}
    </p>

    <ol class="settings__steps">
      <li>
        {{ t('Open zotero.org → Settings → Security → Applications and create a new private key.') }}
      </li>
      <li>{{ t('Allow it to read your personal library, and save it.') }}</li>
      <li>{{ t('Paste it below. It is used for this copy and never stored.') }}</li>
    </ol>
    <p class="settings__detail">
      {{ t('zotero.org has no password sign-in for other programs, which is why this takes a key rather than your zotero.org password.') }}
    </p>

    <template v-if="!running">
      <AppTextField
        v-model="apiKey"
        :label="t('zotero.org API key')"
        autocomplete="off"
        spellcheck="false"
      />

      <label class="settings__check">
        <input v-model="replace" type="checkbox" />
        <span>{{ t('Replace what my library here already holds') }}</span>
      </label>

      <p v-if="replace" class="settings__warning" role="status">
        {{ t('Everything in your library here is deleted first, files included, and there is no trash around it.') }}
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

      <AppButton :loading="starting" :disabled="!apiKey.trim()" @click="begin">
        {{ t('Copy my library') }}
      </AppButton>

      <p class="settings__detail">
        {{ t('Afterwards, Zotero on your computer will notice it is talking to a different account and offer to reset its local data. Let it: everything it needs is now on this server.') }}
      </p>
    </template>

    <div v-if="status" class="settings__progress">
      <p class="settings__entry" role="status">
        {{ stageLabel }} <span v-if="counted">{{ counted }}</span>
      </p>
      <p v-if="status.detail" class="settings__detail">{{ status.detail }}</p>
      <p v-if="running" class="settings__detail">
        {{ t('This can take a while. You can leave this page open or come back to it.') }}
      </p>
      <p v-if="status.error" class="settings__warning" role="alert">{{ status.error }}</p>

      <template v-if="summary && !status.error">
        <p class="settings__detail">
          {{
            t('{items} items, {collections} collections, {tags} tags and {files} files, from {username} at zotero.org.', {
              items: summary.items,
              collections: summary.collections,
              tags: summary.tags,
              files: summary.files,
              username: summary.username || summary.userID,
            })
          }}
        </p>
        <p v-if="summary.rewritten" class="settings__detail">
          {{ t('{count} link between items was pointed at your account here. | {count} links between items were pointed at your account here.', summary.rewritten) }}
        </p>
        <p v-if="summary.unavailable?.length" class="settings__warning">
          {{ t('zotero.org would not serve everything asked of it. The copy is missing {parts} and is otherwise whole.', { parts: summary.unavailable.join(', ') }) }}
        </p>
        <p v-if="summary.filesMissing.length" class="settings__warning">
          {{ t('{count} attachment had no file stored at zotero.org and came across without one. | {count} attachments had no file stored at zotero.org and came across without one.', summary.filesMissing.length) }}
        </p>
        <p v-if="summary.skipped.length" class="settings__warning">
          {{ t('{count} item could not be stored here and was left behind: {keys} | {count} items could not be stored here and were left behind: {keys}', { count: summary.skipped.length, keys: summary.skipped.map((entry) => entry.key).join(', ') }, summary.skipped.length) }}
        </p>
      </template>
    </div>
  </section>
</template>

<style scoped>
@import '@/styles/settings.css';

/* Numbered because the order matters: the key has to exist before it can be
   pasted, and it cannot be made from here. */
.settings__steps {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0;
  padding-left: 1.2rem;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.settings__progress {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
  padding: var(--md-spacing-3);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
}
</style>
