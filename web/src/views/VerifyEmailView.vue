<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

const state = ref<'working' | 'done' | 'failed'>('working')

onMounted(async () => {
  const token = route.query.token
  if (typeof token !== 'string' || !token) {
    state.value = 'failed'
    return
  }
  try {
    await auth.verifyEmail(token)
    state.value = 'done'
  } catch {
    state.value = 'failed'
  }
})
</script>

<template>
  <section class="auth-form">
    <h1>Email address</h1>

    <p v-if="state === 'working'" class="auth-form__lead">Confirming…</p>

    <template v-else-if="state === 'done'">
      <p class="auth-form__lead">
        Confirmed. This address will now receive security notifications and invitations.
      </p>
      <AppButton full-width @click="$router.push({ name: 'library' })">
        Go to your library
      </AppButton>
    </template>

    <template v-else>
      <p class="auth-form__error" role="alert">
        {{ auth.error ?? 'That confirmation link is not valid or has expired.' }}
      </p>
      <!-- Resending needs a session; someone who followed a stale link in
           another browser has to sign in first. -->
      <AppButton v-if="auth.isAuthenticated" full-width @click="auth.resendVerification()">
        Send a new link
      </AppButton>
      <AppButton v-else variant="text" full-width @click="$router.push({ name: 'sign-in' })">
        Sign in
      </AppButton>
    </template>
  </section>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
