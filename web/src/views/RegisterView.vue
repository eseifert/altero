<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()

/** Mirrors the server's floor so the form can say so before a round trip. */
const MINIMUM_PASSWORD_LENGTH = 8

const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const email = ref('')
const displayName = ref('')
const password = ref('')
const repeated = ref('')
const touched = ref(false)

const mismatch = computed(
  () => touched.value && repeated.value.length > 0 && password.value !== repeated.value,
)
const tooShort = computed(
  () => touched.value && password.value.length > 0 && password.value.length < MINIMUM_PASSWORD_LENGTH,
)
const submittable = computed(
  () => password.value.length >= MINIMUM_PASSWORD_LENGTH && password.value === repeated.value,
)

async function submit(): Promise<void> {
  touched.value = true
  if (!submittable.value) {
    return
  }
  try {
    await auth.register({
      username: username.value,
      email: email.value,
      password: password.value,
      displayName: displayName.value,
    })
  } catch {
    return
  }
  await router.push({ name: 'library' })
}
</script>

<template>
  <form class="auth-form" @submit.prevent="submit">
    <h1>{{ t('Create your account') }}</h1>
    <p class="auth-form__lead">
      {{ t('This instance has no accounts yet, so this one will be yours.') }}
    </p>

    <AppTextField
      v-model="username"
      :label="t('Username')"
      autocomplete="username"
      required
      autofocus
    />
    <AppTextField
      v-model="email"
      :label="t('Email address')"
      type="email"
      autocomplete="email"
      required
      :hint="t('Used for security notifications and invitations')"
    />
    <AppTextField
      v-model="displayName"
      :label="t('Display name')"
      autocomplete="name"
      :hint="t('Optional')"
    />
    <AppTextField
      v-model="password"
      :label="t('Password')"
      type="password"
      autocomplete="new-password"
      required
      :hint="t('At least {count} characters', { count: MINIMUM_PASSWORD_LENGTH })"
      :error="
        tooShort ? t('A password must be at least {count} characters', { count: MINIMUM_PASSWORD_LENGTH }) : null
      "
    />
    <AppTextField
      v-model="repeated"
      :label="t('Repeat password')"
      type="password"
      autocomplete="new-password"
      required
      :error="mismatch ? t('The two passwords do not match') : null"
    />

    <p v-if="auth.error" class="auth-form__error" role="alert">{{ auth.error }}</p>

    <AppButton type="submit" full-width :loading="auth.busy">{{ t('Create account') }}</AppButton>

    <p class="auth-form__aside">
      {{ t('Already have an account?') }}
      <RouterLink :to="{ name: 'sign-in' }">{{ t('Sign in') }}</RouterLink>
    </p>
  </form>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
