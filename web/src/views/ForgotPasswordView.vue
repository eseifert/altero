<script setup lang="ts">
/**
 * Asking for a link to set a new password.
 *
 * Unguarded, and it stays on one screen: the answer is the same sentence
 * whatever the server found, because a page that said "no account has that
 * address" would answer, one address at a time, which addresses do -- and the
 * people most likely to ask are not the ones who forgot a password.
 *
 * So the confirmation is written as a conditional rather than a promise. It
 * covers an unknown address, an unconfirmed one, a suspended account, a
 * request already made three times this hour, and a relay that is down, none
 * of which this screen is told apart.
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'

const { t } = useI18n()

const router = useRouter()

const email = ref('')
const busy = ref(false)
const asked = ref(false)
const failure = ref<string | null>(null)

async function submit(): Promise<void> {
  busy.value = true
  failure.value = null
  try {
    await request('/web/auth/forgot', { method: 'POST', body: { email: email.value } })
    asked.value = true
  } catch (thrown) {
    // Only a server that could not be reached lands here; the endpoint itself
    // answers 202 for every outcome it has an opinion about.
    failure.value = thrown instanceof ApiError ? thrown.message : String(thrown)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="auth-form">
    <h1>{{ t('Forgotten password') }}</h1>

    <template v-if="asked">
      <p class="auth-form__lead">
        {{ t('If an account here uses that address, a link to set a new password is on its way.') }}
      </p>
      <p class="auth-form__lead">
        {{ t('The link works once and lasts twelve hours. Your current password still works.') }}
      </p>
      <AppButton variant="text" full-width @click="router.push({ name: 'sign-in' })">
        {{ t('Back to sign in') }}
      </AppButton>
    </template>

    <template v-else>
      <p class="auth-form__lead">
        {{ t('Give the address on your account and we will send a link to set a new one.') }}
      </p>
      <form @submit.prevent="submit">
        <AppTextField
          v-model="email"
          type="email"
          :label="t('Email address')"
          autocomplete="email"
          required
          autofocus
          :error="failure"
        />
        <AppButton type="submit" full-width :disabled="busy || !email">
          {{ t('Send the link') }}
        </AppButton>
      </form>
      <p class="auth-form__aside">
        <RouterLink :to="{ name: 'sign-in' }">{{ t('Back to sign in') }}</RouterLink>
      </p>
    </template>
  </section>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
