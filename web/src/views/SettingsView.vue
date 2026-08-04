<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import type { User } from '@/stores/auth'
import { formatDate, formatDateTime } from '@/formats'

const { t } = useI18n()

interface SessionEntry {
  id: number
  userAgent: string
  created: string
  lastSeen: string
  current: boolean
}

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

interface AccountPayload {
  user: User
  totpEnabled: boolean
  sessions: SessionEntry[]
}

const auth = useAuthStore()

const account = ref<AccountPayload | null>(null)
const notice = ref<string | null>(null)
const failure = ref<string | null>(null)

const displayName = ref('')
const currentPassword = ref('')
const newPassword = ref('')
const newEmail = ref('')
const emailPassword = ref('')
const disablePassword = ref('')

/** Set while enrolling, cleared once the code is confirmed. */
const enrolment = ref<{ secret: string; uri: string } | null>(null)
const enrolmentCode = ref('')

const busy = ref(false)

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
    account.value = await request<AccountPayload>('/web/account')
    displayName.value = account.value.user.displayName
    chosenLanguage.value = account.value.user.language ?? ''
    chosenTimeZone.value = account.value.user.timeZone ?? ''
    keys.value = (await request<{ keys: KeyEntry[] }>('/web/account/keys')).keys
    await loadChoices()
  } catch (thrown) {
    failure.value = message(thrown)
  }
}

function message(thrown: unknown): string {
  return thrown instanceof ApiError ? thrown.message : String(thrown)
}

/** Run one settings action, reporting whichever way it went. */
async function attempt(work: () => Promise<void>, success: string): Promise<void> {
  busy.value = true
  notice.value = null
  failure.value = null
  try {
    await work()
    notice.value = success
    await load()
  } catch (thrown) {
    failure.value = message(thrown)
  } finally {
    busy.value = false
  }
}

const saveName = () =>
  attempt(async () => {
    await request('/web/account', { method: 'PATCH', body: { displayName: displayName.value } })
    await auth.restore()
  }, 'Name saved.')

const savePassword = () =>
  attempt(async () => {
    await request('/web/account/password', {
      method: 'POST',
      body: { currentPassword: currentPassword.value, newPassword: newPassword.value },
    })
    currentPassword.value = ''
    newPassword.value = ''
  }, 'Password changed. Every other browser was signed out.')

const saveEmail = () =>
  attempt(async () => {
    await request('/web/account/email', {
      method: 'POST',
      body: { email: newEmail.value, currentPassword: emailPassword.value },
    })
    emailPassword.value = ''
  }, `Confirmation sent to ${newEmail.value}. The address changes when you follow the link.`)

const startEnrolment = () =>
  attempt(async () => {
    enrolment.value = await request('/web/account/totp', { method: 'POST' })
  }, t('Scan the code below, then enter a code from the app.'))

const confirmEnrolment = () =>
  attempt(async () => {
    await request('/web/account/totp/confirm', {
      method: 'POST',
      body: { code: enrolmentCode.value },
    })
    enrolment.value = null
    enrolmentCode.value = ''
  }, t('Authenticator enabled.'))

const disableTotp = () =>
  attempt(async () => {
    await request('/web/account/totp/disable', {
      method: 'POST',
      body: { currentPassword: disablePassword.value },
    })
    disablePassword.value = ''
  }, t('Authenticator removed.'))

const revokeOthers = () =>
  attempt(
    () => request('/web/account/sessions/revoke-others', { method: 'POST' }),
    t('Signed out everywhere else.'),
  )

const revoke = (id: number) =>
  attempt(
    () => request(`/web/account/sessions/${id}`, { method: 'DELETE' }),
    t('That session was signed out.'),
  )

/* ---- Language and time zone ---- */

const locale = useLocaleStore()
const choices = ref<{ languages: { tag: string; name: string }[]; timeZones: string[] }>({
  languages: [],
  timeZones: [],
})
/* '' is the "follow this device" option: a select cannot hold null, and the
   server reads an empty string as null for exactly this reason. */
const chosenLanguage = ref('')
/** What "follow this device" resolves to here, so the option can say so. */
const automaticLanguage = computed(
  () =>
    choices.value.languages.find((entry) => entry.tag === locale.active)?.name ?? locale.active,
)
const chosenTimeZone = ref('')

async function loadChoices(): Promise<void> {
  choices.value = await request('/web/account/locales')
}

const saveLocale = () =>
  attempt(async () => {
    await request('/web/account/locale', {
      method: 'PUT',
      body: { language: chosenLanguage.value || null, timeZone: chosenTimeZone.value || null },
    })
    locale.adopt({
      language: chosenLanguage.value || null,
      timeZone: chosenTimeZone.value || null,
    })
  }, t('Language and time zone saved.'))

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
  }, t('Key created. Copy it now — it is not shown again.'))

const revokeKey = (id: number, name: string) =>
  attempt(
    () => request(`/web/account/keys/${id}`, { method: 'DELETE' }),
    t('“{name}” was revoked and stops working immediately.', { name }),
  )

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
  <section class="settings">
    <h1>{{ t('Settings') }}</h1>

    <p v-if="notice" class="settings__notice">{{ notice }}</p>
    <p v-if="failure" class="settings__failure" role="alert">{{ failure }}</p>

    <section class="settings__card">
      <h2>{{ t('Profile') }}</h2>
      <p class="settings__detail">
        {{ t('Signed in as {username}.', { username: account?.user.username ?? '' }) }}
      </p>
      <AppTextField v-model="displayName" :label="t('Display name')" />
      <AppButton :loading="busy" @click="saveName">{{ t('Save') }}</AppButton>
    </section>

    <section class="settings__card">
      <h2>{{ t('Email address') }}</h2>
      <p class="settings__detail">
        {{ account?.user.email }}
        <span v-if="account?.user.emailVerified"> — {{ t('confirmed') }}</span>
        <span v-else> — {{ t('not confirmed yet') }}</span>
      </p>
      <AppTextField
        v-model="newEmail"
        :label="t('New address')"
        type="email"
        autocomplete="email"
      />
      <AppTextField
        v-model="emailPassword"
        :label="t('Current password')"
        type="password"
        autocomplete="current-password"
      />
      <AppButton :loading="busy" @click="saveEmail">{{ t('Send confirmation') }}</AppButton>
    </section>

    <section class="settings__card">
      <h2>{{ t('Password') }}</h2>
      <AppTextField
        v-model="currentPassword"
        :label="t('Current password')"
        type="password"
        autocomplete="current-password"
      />
      <AppTextField
        v-model="newPassword"
        :label="t('New password')"
        type="password"
        autocomplete="new-password"
        :hint="t('At least {count} characters', { count: 8 })"
      />
      <AppButton :loading="busy" @click="savePassword">{{ t('Change password') }}</AppButton>
    </section>

    <section class="settings__card">
      <h2>{{ t('Authenticator app') }}</h2>

      <template v-if="account?.totpEnabled">
        <p class="settings__detail">{{ t('Signing in asks for a code.') }}</p>
        <AppTextField
          v-model="disablePassword"
          :label="t('Current password')"
          type="password"
          autocomplete="current-password"
        />
        <AppButton variant="outlined" :loading="busy" @click="disableTotp">
          {{ t('Remove authenticator') }}
        </AppButton>
      </template>

      <template v-else-if="enrolment">
        <p class="settings__detail">
          {{
            t('Add this secret to your authenticator app, then enter the code it shows. Nothing changes until you do.')
          }}
        </p>
        <code class="settings__secret">{{ enrolment.secret }}</code>
        <AppTextField
          v-model="enrolmentCode"
          :label="t('Code from the app')"
          inputmode="numeric"
        />
        <AppButton :loading="busy" @click="confirmEnrolment">{{ t('Turn on') }}</AppButton>
      </template>

      <template v-else>
        <p class="settings__detail">{{ t('Not enabled.') }}</p>
        <AppButton variant="tonal" :loading="busy" @click="startEnrolment">
          {{ t('Set up an authenticator') }}
        </AppButton>
      </template>
    </section>

    <section class="settings__card">
      <h2>{{ t('Language and time zone') }}</h2>
      <p class="settings__detail">
        {{ t('Both follow this device unless you choose otherwise, and travel with your account.') }}
      </p>

      <label class="settings__field">
        <span class="settings__field-label">{{ t('Language') }}</span>
        <select v-model="chosenLanguage" class="settings__select">
          <option value="">
            {{ t('Follow this device ({name})', { name: automaticLanguage }) }}
          </option>
          <option v-for="entry in choices.languages" :key="entry.tag" :value="entry.tag">
            {{ entry.name }}
          </option>
        </select>
      </label>

      <label class="settings__field">
        <span class="settings__field-label">{{ t('Time zone') }}</span>
        <select v-model="chosenTimeZone" class="settings__select">
          <option value="">
            {{ t('Follow this device ({name})', { name: locale.browserTimeZone }) }}
          </option>
          <option v-for="zone in choices.timeZones" :key="zone" :value="zone">{{ zone }}</option>
        </select>
      </label>

      <p class="settings__detail">
        {{ t('Dates look like this: {example}', { example: formatDateTime(new Date()) }) }}
      </p>

      <AppButton :loading="busy" @click="saveLocale">{{ t('Save') }}</AppButton>
    </section>

    <section class="settings__card">
      <h2>{{ t('API keys') }}</h2>
      <p class="settings__detail">
        {{
          t('What the Zotero app and any scripts use to sync. Linking Zotero from its own settings creates one of these for you.')
        }}
      </p>

      <ul v-if="keys.length" class="settings__sessions">
        <li v-for="entry in keys" :key="entry.id">
          <div>
            <p class="settings__session">
              {{ entry.name }}
              <code class="settings__suffix">…{{ entry.suffix }}</code>
            </p>
            <p class="settings__detail">{{ t('{what} · created {when}', { what: describe(entry), when: when(entry.created) }) }}</p>
            <p class="settings__detail settings__usage">{{ lastSeen(entry) }}</p>
          </div>
          <AppButton variant="text" @click="revokeKey(entry.id, entry.name)">{{ t('Revoke') }}</AppButton>
        </li>
      </ul>
      <p v-else class="settings__detail">{{ t('No keys yet.') }}</p>

      <!-- Shown once. The server masks every key after this response. -->
      <div v-if="issuedKey" class="settings__issued">
        <p class="settings__detail">{{ t('Copy this now. It will not be shown again.') }}</p>
        <code class="settings__secret">{{ issuedKey }}</code>
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

    <section class="settings__card">
      <h2>{{ t('Signed-in browsers') }}</h2>
      <ul class="settings__sessions">
        <li v-for="entry in account?.sessions ?? []" :key="entry.id">
          <div>
            <p class="settings__session">
              {{ entry.userAgent || t('Unknown browser') }}
              <span v-if="entry.current" class="settings__badge">{{ t('this one') }}</span>
            </p>
            <p class="settings__detail">
              {{ t('Last used {when}', { when: when(entry.lastSeen) }) }}
            </p>
          </div>
          <AppButton v-if="!entry.current" variant="text" @click="revoke(entry.id)">
            {{ t('Sign out') }}
          </AppButton>
        </li>
      </ul>
      <AppButton
        v-if="(account?.sessions?.length ?? 0) > 1"
        variant="outlined"
        :loading="busy"
        @click="revokeOthers"
      >
        {{ t('Sign out everywhere else') }}
      </AppButton>
    </section>
  </section>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  max-width: 34rem;
}

.settings__field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.settings__field-label {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.settings__select {
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: inherit;
  font: inherit;
}

.settings__card {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-5);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
}

.settings__card h2 {
  margin: 0;
  font-size: var(--md-sys-typescale-title-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.settings__card :deep(.app-button) {
  align-self: flex-start;
}

.settings__detail {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.settings__notice,
.settings__failure {
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.settings__notice {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.settings__failure {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

.settings__secret {
  padding: var(--md-spacing-3);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface-container);
  font-family: var(--md-sys-typescale-font-mono);
  letter-spacing: 0.08em;
  word-break: break-all;
}

.settings__sessions {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
}

.settings__sessions li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-3);
}

.settings__session {
  margin: 0;
}

.settings__usage {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 26rem;
}

.settings__suffix {
  margin-left: var(--md-spacing-2);
  padding: 1px 6px;
  border-radius: var(--md-sys-shape-corner-extra-small);
  background: var(--md-sys-color-surface-container);
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

.settings__check {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  font-size: var(--md-sys-typescale-body-medium-size);
  color: var(--md-sys-color-on-surface-variant);
}

.settings__check input {
  accent-color: var(--md-sys-color-primary);
  width: 18px;
  height: 18px;
}

.settings__badge {
  margin-left: var(--md-spacing-2);
  padding: 2px 8px;
  border-radius: var(--md-sys-shape-corner-full);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  font-size: var(--md-sys-typescale-label-medium-size);
}
</style>
