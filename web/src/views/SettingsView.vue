<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'
import type { User } from '@/stores/auth'

interface SessionEntry {
  id: number
  userAgent: string
  created: string
  lastSeen: string
  current: boolean
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

onMounted(load)

async function load(): Promise<void> {
  try {
    account.value = await request<AccountPayload>('/web/account')
    displayName.value = account.value.user.displayName
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
  }, 'Scan the code below, then enter a code from the app.')

const confirmEnrolment = () =>
  attempt(async () => {
    await request('/web/account/totp/confirm', {
      method: 'POST',
      body: { code: enrolmentCode.value },
    })
    enrolment.value = null
    enrolmentCode.value = ''
  }, 'Authenticator enabled.')

const disableTotp = () =>
  attempt(async () => {
    await request('/web/account/totp/disable', {
      method: 'POST',
      body: { currentPassword: disablePassword.value },
    })
    disablePassword.value = ''
  }, 'Authenticator removed.')

const revokeOthers = () =>
  attempt(
    () => request('/web/account/sessions/revoke-others', { method: 'POST' }),
    'Signed out everywhere else.',
  )

const revoke = (id: number) =>
  attempt(
    () => request(`/web/account/sessions/${id}`, { method: 'DELETE' }),
    'That session was signed out.',
  )

function when(iso: string): string {
  return new Date(iso).toLocaleString()
}
</script>

<template>
  <section class="settings">
    <h1>Settings</h1>

    <p v-if="notice" class="settings__notice">{{ notice }}</p>
    <p v-if="failure" class="settings__failure" role="alert">{{ failure }}</p>

    <section class="settings__card">
      <h2>Profile</h2>
      <p class="settings__detail">Signed in as {{ account?.user.username }}.</p>
      <AppTextField v-model="displayName" label="Display name" />
      <AppButton :loading="busy" @click="saveName">Save</AppButton>
    </section>

    <section class="settings__card">
      <h2>Email address</h2>
      <p class="settings__detail">
        {{ account?.user.email }}
        <span v-if="account?.user.emailVerified"> — confirmed</span>
        <span v-else> — not confirmed yet</span>
      </p>
      <AppTextField v-model="newEmail" label="New address" type="email" autocomplete="email" />
      <AppTextField
        v-model="emailPassword"
        label="Current password"
        type="password"
        autocomplete="current-password"
      />
      <AppButton :loading="busy" @click="saveEmail">Send confirmation</AppButton>
    </section>

    <section class="settings__card">
      <h2>Password</h2>
      <AppTextField
        v-model="currentPassword"
        label="Current password"
        type="password"
        autocomplete="current-password"
      />
      <AppTextField
        v-model="newPassword"
        label="New password"
        type="password"
        autocomplete="new-password"
        hint="At least 8 characters"
      />
      <AppButton :loading="busy" @click="savePassword">Change password</AppButton>
    </section>

    <section class="settings__card">
      <h2>Authenticator app</h2>

      <template v-if="account?.totpEnabled">
        <p class="settings__detail">Signing in asks for a code.</p>
        <AppTextField
          v-model="disablePassword"
          label="Current password"
          type="password"
          autocomplete="current-password"
        />
        <AppButton variant="outlined" :loading="busy" @click="disableTotp">
          Remove authenticator
        </AppButton>
      </template>

      <template v-else-if="enrolment">
        <p class="settings__detail">
          Add this secret to your authenticator app, then enter the code it shows. Nothing
          changes until you do.
        </p>
        <code class="settings__secret">{{ enrolment.secret }}</code>
        <AppTextField v-model="enrolmentCode" label="Code from the app" inputmode="numeric" />
        <AppButton :loading="busy" @click="confirmEnrolment">Turn on</AppButton>
      </template>

      <template v-else>
        <p class="settings__detail">Not enabled.</p>
        <AppButton variant="tonal" :loading="busy" @click="startEnrolment">
          Set up an authenticator
        </AppButton>
      </template>
    </section>

    <section class="settings__card">
      <h2>Signed-in browsers</h2>
      <ul class="settings__sessions">
        <li v-for="entry in account?.sessions ?? []" :key="entry.id">
          <div>
            <p class="settings__session">
              {{ entry.userAgent || 'Unknown browser' }}
              <span v-if="entry.current" class="settings__badge">this one</span>
            </p>
            <p class="settings__detail">Last used {{ when(entry.lastSeen) }}</p>
          </div>
          <AppButton v-if="!entry.current" variant="text" @click="revoke(entry.id)">
            Sign out
          </AppButton>
        </li>
      </ul>
      <AppButton
        v-if="(account?.sessions?.length ?? 0) > 1"
        variant="outlined"
        :loading="busy"
        @click="revokeOthers"
      >
        Sign out everywhere else
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

.settings__badge {
  margin-left: var(--md-spacing-2);
  padding: 2px 8px;
  border-radius: var(--md-sys-shape-corner-full);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  font-size: var(--md-sys-typescale-label-medium-size);
}
</style>
