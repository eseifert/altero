<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'

/** Mirrors the server's floor so the form can say so before a round trip. */
const MINIMUM_PASSWORD_LENGTH = 8

const auth = useAuthStore()
const router = useRouter()

const username = ref('')
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
    <h1>Create your account</h1>
    <p class="auth-form__lead">This instance has no accounts yet, so this one will be yours.</p>

    <AppTextField v-model="username" label="Username" autocomplete="username" required autofocus />
    <AppTextField v-model="displayName" label="Display name" autocomplete="name" hint="Optional" />
    <AppTextField
      v-model="password"
      label="Password"
      type="password"
      autocomplete="new-password"
      required
      :hint="`At least ${MINIMUM_PASSWORD_LENGTH} characters`"
      :error="tooShort ? `A password must be at least ${MINIMUM_PASSWORD_LENGTH} characters` : null"
    />
    <AppTextField
      v-model="repeated"
      label="Repeat password"
      type="password"
      autocomplete="new-password"
      required
      :error="mismatch ? 'The two passwords do not match' : null"
    />

    <p v-if="auth.error" class="auth-form__error" role="alert">{{ auth.error }}</p>

    <AppButton type="submit" full-width :loading="auth.busy">Create account</AppButton>

    <p class="auth-form__aside">
      Already have an account?
      <RouterLink :to="{ name: 'sign-in' }">Sign in</RouterLink>
    </p>
  </form>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
