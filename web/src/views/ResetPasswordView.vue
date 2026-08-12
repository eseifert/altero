<script setup lang="ts">
/**
 * Setting a password from a link an administrator issued.
 *
 * Unguarded, like the confirmation link: it is followed in whatever browser
 * happens to be open, frequently not the one that will use the account, and
 * the token in it is the whole credential.
 *
 * The account is named before a password is asked for, so somebody who was
 * sent the wrong link sees that before typing anything, and an expired one
 * says so rather than taking a password and then refusing it.
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const state = ref<'checking' | 'ready' | 'done' | 'failed'>('checking')
const account = ref<{ username: string; displayName: string } | null>(null)
const password = ref('')
const busy = ref(false)
const failure = ref<string | null>(null)

const token = () => (typeof route.query.token === 'string' ? route.query.token : '')

function message(thrown: unknown): string {
  return thrown instanceof ApiError ? thrown.message : String(thrown)
}

onMounted(async () => {
  if (!token()) {
    state.value = 'failed'
    return
  }
  try {
    account.value = await request(`/web/auth/reset/${encodeURIComponent(token())}`)
    state.value = 'ready'
  } catch (thrown) {
    failure.value = message(thrown)
    state.value = 'failed'
  }
})

async function submit(): Promise<void> {
  busy.value = true
  failure.value = null
  try {
    await request('/web/auth/reset', {
      method: 'POST',
      body: { token: token(), password: password.value },
    })
    state.value = 'done'
  } catch (thrown) {
    // The link is not spent by a password the server refused, so the form
    // stays open rather than sending somebody back to ask for another link.
    failure.value = message(thrown)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="auth-form">
    <h1>{{ t('Set a password') }}</h1>

    <p v-if="state === 'checking'" class="auth-form__lead">{{ t('Checking the link…') }}</p>

    <template v-else-if="state === 'ready'">
      <p class="auth-form__lead">
        {{ t('Setting the password for {username}.', { username: account?.username }) }}
      </p>
      <form @submit.prevent="submit">
        <AppTextField
          v-model="password"
          type="password"
          :label="t('New password')"
          autocomplete="new-password"
          :error="failure"
        />
        <AppButton type="submit" full-width :disabled="busy || !password">
          {{ t('Set password') }}
        </AppButton>
      </form>
    </template>

    <template v-else-if="state === 'done'">
      <p class="auth-form__lead">
        {{ t('Password set. Every other signed-in browser was signed out.') }}
      </p>
      <AppButton full-width @click="router.push({ name: 'sign-in' })">{{ t('Sign in') }}</AppButton>
    </template>

    <template v-else>
      <p class="auth-form__error" role="alert">
        {{ failure ?? t('That link is not valid or has expired.') }}
      </p>
      <!-- Where the instance offers the form, sending somebody to it is more
           use than telling them to find an administrator. -->
      <p v-if="auth.passwordResetOpen" class="auth-form__lead">
        {{ t('Ask for a new one. Your current password still works.') }}
      </p>
      <p v-else class="auth-form__lead">
        {{ t('Ask whoever runs this server for a new one. Your current password still works.') }}
      </p>
      <AppButton
        v-if="auth.passwordResetOpen"
        variant="text"
        full-width
        @click="router.push({ name: 'forgot-password' })"
      >
        {{ t('Forgotten password?') }}
      </AppButton>
      <AppButton variant="text" full-width @click="router.push({ name: 'sign-in' })">
        {{ t('Sign in') }}
      </AppButton>
    </template>
  </section>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
