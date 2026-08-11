<script setup lang="ts">
/**
 * The API keys on the account: what each may do, and what it has been doing.
 *
 * The list is loaded here rather than with the account, so that opening
 * settings to change a display name does not ask the server for credentials
 * nobody is looking at.
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { formatDate, formatDateTime } from '@/formats'
import { message, usePanel } from './panel'

const { t } = useI18n()

interface KeyEntry {
  id: number
  name: string
  suffix: string
  created: string | null
  lastUsed: string | null
  lastAddress: string | null
  lastUserAgent: string | null
  access: { write: boolean; groups: boolean }
}

const { busy, failure, attempt } = usePanel()

const keys = ref<KeyEntry[]>([])
const newKeyName = ref('')
const newKeyPassword = ref('')
const newKeyWrite = ref(true)
const newKeyGroups = ref(true)
/** Held only until the page is left: the server will not show it again. */
const issuedKey = ref<string | null>(null)

onMounted(load)

async function load(): Promise<void> {
  try {
    keys.value = (await request<{ keys: KeyEntry[] }>('/web/account/keys')).keys
  } catch (thrown) {
    failure.value = message(thrown)
  }
}

const createKey = () =>
  attempt(async () => {
    const response = await request<{ key: string }>('/web/account/keys', {
      method: 'POST',
      body: {
        name: newKeyName.value,
        currentPassword: newKeyPassword.value,
        write: newKeyWrite.value,
        groups: newKeyGroups.value,
      },
    })
    issuedKey.value = response.key
    newKeyName.value = ''
    newKeyPassword.value = ''
    await load()
  }, t('Key created. Copy it now — it is not shown again.'))

const revokeKey = (id: number, name: string) =>
  attempt(async () => {
    await request(`/web/account/keys/${id}`, { method: 'DELETE' })
    await load()
  }, t('“{name}” was revoked and stops working immediately.', { name }))

function when(iso: string | null): string {
  return iso ? formatDate(iso) : t('date unknown')
}

function describe(entry: KeyEntry): string {
  const scope = entry.access.write ? t('Read and write') : t('Read only')
  return entry.access.groups
    ? t('{scope}, including groups', { scope })
    : t('{scope}, personal library only', { scope })
}

/**
 * What a key has been doing, in one line.
 *
 * "Never used" is said outright rather than left blank: a key that has never
 * been used is the clearest candidate for revoking, and an empty cell reads as
 * missing information instead of as an answer.
 */
function lastSeen(entry: KeyEntry): string {
  if (!entry.lastUsed) {
    return t('Never used')
  }
  const when = t('Last used {when}', { when: formatDateTime(entry.lastUsed) })
  const where = entry.lastAddress ? t(' from {address}', { address: entry.lastAddress }) : ''
  const what = entry.lastUserAgent ? ` · ${entry.lastUserAgent}` : ''
  return `${when}${where}${what}`
}
</script>

<template>
  <!-- The heading above names the section; this card is all of it. -->
  <section class="card">
    <p class="settings__detail">
      {{
        t('What the Zotero app and any scripts use to sync. Linking Zotero from its own settings creates one of these for you.')
      }}
    </p>

    <ul v-if="keys.length" class="settings__list">
      <li v-for="entry in keys" :key="entry.id">
        <div>
          <p class="settings__entry">
            {{ entry.name }}
            <code class="chip settings__suffix">…{{ entry.suffix }}</code>
          </p>
          <p class="settings__detail">
            {{ t('{what} · created {when}', { what: describe(entry), when: when(entry.created) }) }}
          </p>
          <p class="settings__detail settings__usage">{{ lastSeen(entry) }}</p>
        </div>
        <AppButton variant="text" @click="revokeKey(entry.id, entry.name)">
          {{ t('Revoke') }}
        </AppButton>
      </li>
    </ul>
    <p v-else class="settings__detail">{{ t('No keys yet.') }}</p>

    <!-- Shown once. The server masks every key after this response. -->
    <div v-if="issuedKey" class="settings__issued">
      <p class="settings__detail">{{ t('Copy this now. It will not be shown again.') }}</p>
      <code class="card__inset settings__secret">{{ issuedKey }}</code>
      <AppButton variant="text" @click="issuedKey = null">{{ t('Done') }}</AppButton>
    </div>

    <details class="settings__new-key">
      <summary>{{ t('Create a key') }}</summary>
      <div class="settings__new-key-body">
        <AppTextField
          v-model="newKeyName"
          :label="t('What is it for?')"
          :hint="t('For example, my laptop')"
        />
        <label class="settings__check">
          <input v-model="newKeyWrite" type="checkbox" />
          <span>{{ t('Allow changes (Zotero needs this to sync)') }}</span>
        </label>
        <label class="settings__check">
          <input v-model="newKeyGroups" type="checkbox" />
          <span>{{ t('Include group libraries') }}</span>
        </label>
        <AppTextField
          v-model="newKeyPassword"
          :label="t('Current password')"
          type="password"
          autocomplete="current-password"
        />
        <AppButton :loading="busy" @click="createKey">{{ t('Create key') }}</AppButton>
      </div>
    </details>
  </section>
</template>

<style scoped>
@import '@/styles/settings.css';

.settings__usage {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 26rem;
}

.settings__suffix {
  margin-left: var(--md-spacing-2);
  font-family: var(--md-sys-typescale-font-mono);
  font-size: var(--md-sys-typescale-body-small-size);
  color: var(--md-sys-color-on-surface-variant);
}

.settings__issued {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
  padding: var(--md-spacing-4);
  border: 1px solid var(--md-sys-color-primary);
  border-radius: var(--md-sys-shape-corner-small);
}

.settings__new-key summary {
  cursor: pointer;
  color: var(--md-sys-color-primary);
  font-size: var(--md-sys-typescale-label-large-size);
}

.settings__new-key-body {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding-top: var(--md-spacing-3);
}
</style>
