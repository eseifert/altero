<script setup lang="ts">
/** Who the account is: the name it shows and the address it answers at. */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'
import type { Visibility } from '@/stores/profile'
import { usePanel } from './panel'

const { t } = useI18n()

const auth = useAuthStore()
const { account, busy, attempt } = usePanel()

const displayName = ref('')
const newEmail = ref('')
const emailPassword = ref('')

/**
 * Who may read the profile page, and the sentence each choice makes.
 *
 * Three answers rather than a switch, because the middle one is the reason the
 * setting exists: an instance shared by a research group is neither the open
 * web nor a private drive. `public` is first and is what every account starts
 * as -- it is what publishing means upstream, and what the desktop client's
 * wizard says will happen.
 */
const AUDIENCES: { value: Visibility; label: () => string; detail: () => string }[] = [
  {
    value: 'public',
    label: () => t('Anyone'),
    detail: () => t('Your published work can be read by anyone, without an account here.'),
  },
  {
    value: 'users',
    label: () => t('People with an account here'),
    detail: () => t('Your published work can be read by anyone signed in to this server.'),
  },
  {
    value: 'private',
    label: () => t('Nobody'),
    detail: () =>
      t('Your page is hidden. Your items stay in My Publications, so it can be opened again.'),
  },
]

const visibility = ref<Visibility>('public')

/* The account arrives after the section is drawn, and again after every save,
   so the field follows it rather than being filled in once on mount. */
watch(
  account,
  (loaded) => {
    if (loaded) {
      displayName.value = loaded.user.displayName
      visibility.value = loaded.user.profileVisibility
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

/* Saved on the change rather than behind a button: there is one control, and a
   radio somebody has already moved with a Save beside it reads as unsaved for
   as long as they leave it there.

   Moved here first so the control answers the click, and moved back if the
   save is refused — a radio resting on a choice the server did not accept is a
   screen saying the page is hidden when it is not. */
const saveVisibility = (chosen: Visibility) => {
  const before = visibility.value
  visibility.value = chosen
  return attempt(async () => {
    try {
      await request('/web/account', { method: 'PATCH', body: { profileVisibility: chosen } })
    } catch (thrown) {
      visibility.value = before
      throw thrown
    }
    await auth.restore()
  }, t('Saved.'))
}

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

  <!--
    The public page, and who may read it. It sits under the name because it is
    the same question continued: this is how you appear to other people.
  -->
  <section class="settings__card">
    <h2>{{ t('Public page') }}</h2>
    <p class="settings__detail">
      {{ t('The work you add to My Publications is shown on your public page.') }}
      <RouterLink
        v-if="account"
        :to="{ name: 'profile', params: { username: account.user.username } }"
      >
        {{ t('See your page') }}
      </RouterLink>
    </p>
    <fieldset class="audience">
      <legend class="audience__legend">{{ t('Who can see it') }}</legend>
      <label v-for="choice in AUDIENCES" :key="choice.value" class="audience__choice">
        <input
          type="radio"
          name="profile-visibility"
          :value="choice.value"
          :checked="visibility === choice.value"
          :disabled="busy"
          @change="saveVisibility(choice.value)"
        />
        <span>
          <span class="audience__label">{{ choice.label() }}</span>
          <span class="audience__detail">{{ choice.detail() }}</span>
        </span>
      </label>
    </fieldset>
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

.audience {
  margin: 0;
  padding: 0;
  border: none;
}

.audience__legend {
  padding: 0;
  margin-bottom: var(--md-spacing-2);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.audience__choice {
  display: flex;
  align-items: flex-start;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-2) 0;
  cursor: pointer;
}

.audience__label,
.audience__detail {
  display: block;
}

.audience__detail {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}
</style>
