<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')

async function submit(): Promise<void> {
  try {
    await auth.login(username.value, password.value)
  } catch {
    // The store keeps the message; the form shows it below.
    return
  }
  // A second factor short-circuits to its own screen rather than the library,
  // which the session is not yet allowed to read.
  if (auth.needsFactor) {
    await router.push({ name: 'second-factor' })
    return
  }
  await router.push((route.query.next as string) || { name: 'library' })
}
</script>

<template>
  <form class="auth-form" @submit.prevent="submit">
    <h1>Sign in</h1>
    <p class="auth-form__lead">to your altero library</p>

    <AppTextField
      v-model="username"
      label="Username"
      autocomplete="username"
      required
      autofocus
    />
    <AppTextField
      v-model="password"
      label="Password"
      type="password"
      autocomplete="current-password"
      required
    />

    <p v-if="auth.error" class="auth-form__error" role="alert">{{ auth.error }}</p>

    <AppButton type="submit" full-width :loading="auth.busy">Sign in</AppButton>

    <p v-if="auth.registrationOpen" class="auth-form__aside">
      No account yet?
      <RouterLink :to="{ name: 'register' }">Create one</RouterLink>
    </p>
  </form>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
