<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const code = ref('')

async function submit(): Promise<void> {
  try {
    await auth.submitFactor(code.value)
  } catch {
    code.value = ''
    return
  }
  await router.push({ name: 'library' })
}
</script>

<template>
  <form class="auth-form" @submit.prevent="submit">
    <h1>One more step</h1>
    <p class="auth-form__lead">Enter the six-digit code from your authenticator app.</p>

    <AppTextField
      v-model="code"
      label="Code"
      inputmode="numeric"
      autocomplete="one-time-code"
      required
      autofocus
    />

    <p v-if="auth.error" class="auth-form__error" role="alert">{{ auth.error }}</p>

    <AppButton type="submit" full-width :loading="auth.busy">Verify</AppButton>
  </form>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
