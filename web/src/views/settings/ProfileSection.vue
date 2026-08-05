<script setup lang="ts">
/** Who the account is: the name it shows and the address it answers at. */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'
import { usePanel } from './panel'

const { t } = useI18n()

const auth = useAuthStore()
const { account, busy, attempt } = usePanel()

const displayName = ref('')
const newEmail = ref('')
const emailPassword = ref('')

/* The account arrives after the section is drawn, and again after every save,
   so the field follows it rather than being filled in once on mount. */
watch(
  account,
  (loaded) => {
    if (loaded) {
      displayName.value = loaded.user.displayName
    }
  },
  { immediate: true },
)

const saveName = () =>
  attempt(async () => {
    await request('/web/account', { method: 'PATCH', body: { displayName: displayName.value } })
    // The header shows the name too; without this it shows the old one until
    // the next full load.
    await auth.restore()
  }, t('Name saved.'))

const saveEmail = () =>
  attempt(async () => {
    await request('/web/account/email', {
      method: 'POST',
      body: { email: newEmail.value, currentPassword: emailPassword.value },
    })
    emailPassword.value = ''
    // Read before the field is cleared, and interpolated rather than glued on:
    // this sentence was the one message on the screen that was never
    // translated, because it was assembled with a template literal.
  }, t('Confirmation sent to {address}. The address changes when you follow the link.', { address: newEmail.value }))
</script>

<template>
  <!-- "Name" rather than "Profile": the panel and the heading above already
       say which section this is, and a card that repeats it reads as a
       mistake. -->
  <section class="settings__card">
    <h2>{{ t('Name') }}</h2>
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
    <AppTextField v-model="newEmail" :label="t('New address')" type="email" autocomplete="email" />
    <AppTextField
      v-model="emailPassword"
      :label="t('Current password')"
      type="password"
      autocomplete="current-password"
    />
    <AppButton :loading="busy" @click="saveEmail">{{ t('Send confirmation') }}</AppButton>
  </section>
</template>

<style scoped>
@import '@/styles/settings.css';
</style>
