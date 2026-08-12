<script setup lang="ts">
/**
 * Everything that decides who gets in: the password, the authenticator, and
 * the browsers currently holding a session.
 *
 * They are one section because they are one question — who can sign in as me,
 * and what do I do about it — and because the answer to "sign out everywhere"
 * is usually followed by "change the password".
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { formatDate } from '@/formats'
import { usePanel } from './panel'

const { t } = useI18n()

const { account, busy, attempt } = usePanel()

const currentPassword = ref('')
const newPassword = ref('')
const disablePassword = ref('')
const emailCodePassword = ref('')

/** Set while enrolling, cleared once the code is confirmed. */
const enrolment = ref<{ secret: string; uri: string } | null>(null)
const enrolmentCode = ref('')

const savePassword = () =>
  attempt(async () => {
    await request('/web/account/password', {
      method: 'POST',
      body: { currentPassword: currentPassword.value, newPassword: newPassword.value },
    })
    currentPassword.value = ''
    newPassword.value = ''
  }, t('Password changed. Every other browser was signed out.'))

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

const enableEmailCodes = () =>
  attempt(async () => {
    await request('/web/account/email-codes', {
      method: 'POST',
      body: { currentPassword: emailCodePassword.value },
    })
    emailCodePassword.value = ''
  }, t('Codes by email turned on.'))

const disableEmailCodes = () =>
  attempt(async () => {
    await request('/web/account/email-codes', {
      method: 'DELETE',
      body: { currentPassword: emailCodePassword.value },
    })
    emailCodePassword.value = ''
  }, t('Codes by email turned off.'))

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

function when(iso: string | null): string {
  return iso ? formatDate(iso) : t('date unknown')
}
</script>

<template>
  <section class="card">
    <h2 class="card__title">{{ t('Password') }}</h2>
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

  <section class="card">
    <h2 class="card__title">{{ t('Authenticator app') }}</h2>

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
      <code class="card__inset settings__secret">{{ enrolment.secret }}</code>
      <AppTextField v-model="enrolmentCode" :label="t('Code from the app')" inputmode="numeric" />
      <AppButton :loading="busy" @click="confirmEnrolment">{{ t('Turn on') }}</AppButton>
    </template>

    <template v-else>
      <p class="settings__detail">{{ t('Not enabled.') }}</p>
      <AppButton variant="tonal" :loading="busy" @click="startEnrolment">
        {{ t('Set up an authenticator') }}
      </AppButton>
    </template>
  </section>

  <section class="card">
    <h2 class="card__title">{{ t('Codes by email') }}</h2>

    <template v-if="account?.emailCodesEnabled">
      <p class="settings__detail">{{ t('Signing in asks for a code sent to your address.') }}</p>
      <AppTextField
        v-model="emailCodePassword"
        :label="t('Current password')"
        type="password"
        autocomplete="current-password"
      />
      <AppButton variant="outlined" :loading="busy" @click="disableEmailCodes">
        {{ t('Turn off codes by email') }}
      </AppButton>
    </template>

    <template v-else-if="account?.user.emailVerified">
      <p class="settings__detail">
        {{
          t('A second factor for anyone without an authenticator app, and the way back in if you lose the one you have.')
        }}
      </p>
      <AppTextField
        v-model="emailCodePassword"
        :label="t('Current password')"
        type="password"
        autocomplete="current-password"
      />
      <AppButton variant="tonal" :loading="busy" @click="enableEmailCodes">
        {{ t('Turn on codes by email') }}
      </AppButton>
    </template>

    <template v-else>
      <!-- Codes sent to an address nobody has proved they can read would be a
           second factor in name only, so the server refuses; saying so here is
           better than offering a button that answers 400. -->
      <p class="settings__detail">
        {{ t('Confirm your email address first, so the codes go somewhere you can read.') }}
      </p>
    </template>
  </section>

  <section class="card">
    <h2 class="card__title">{{ t('Signed-in browsers') }}</h2>
    <ul class="settings__list">
      <li v-for="entry in account?.sessions ?? []" :key="entry.id">
        <div>
          <p class="settings__entry">
            {{ entry.userAgent || t('Unknown browser') }}
            <span v-if="entry.current" class="chip">{{ t('this one') }}</span>
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
</template>

<style scoped>
@import '@/styles/settings.css';
</style>
