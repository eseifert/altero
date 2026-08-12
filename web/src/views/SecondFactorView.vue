<script setup lang="ts">
/**
 * The second step of signing in.
 *
 * One screen for both factors, because from here they are the same act: six
 * digits, typed in. What differs is where the digits came from and therefore
 * what the screen should say to look for — an app or an inbox — and whether
 * there is anything to offer somebody who cannot reach the one being asked for.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import * as passkeys from '@/passkeys'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()

const auth = useAuthStore()
const router = useRouter()

const code = ref('')
const resent = ref(false)

const byEmail = computed(() => auth.needsFactor === 'email')
const canUsePasskey = computed(() => auth.passkeysAvailable && passkeys.available())

/* A passkey answers this too, for the account that would rather touch a key
   than read a code. */
async function withPasskey(): Promise<void> {
  try {
    await auth.submitFactorWithPasskey()
  } catch {
    return
  }
  await router.push({ name: 'library' })
}
const canSwitchToEmail = computed(() => auth.alternativeFactors.includes('email'))

async function submit(): Promise<void> {
  try {
    await auth.submitFactor(code.value)
  } catch {
    code.value = ''
    return
  }
  await router.push({ name: 'library' })
}

/* The answer to a lost phone. Switching sends a code, so the field the person
   is already looking at goes on being the field they type into. */
async function useEmailInstead(): Promise<void> {
  code.value = ''
  resent.value = false
  await auth.chooseFactor('email')
}

async function resend(): Promise<void> {
  await auth.resendCode()
  resent.value = true
}
</script>

<template>
  <form class="auth-form" @submit.prevent="submit">
    <h1>{{ t('One more step') }}</h1>
    <p v-if="byEmail" class="auth-form__lead">
      {{ t('Enter the six-digit code we sent to your email address.') }}
    </p>
    <p v-else class="auth-form__lead">
      {{ t('Enter the six-digit code from your authenticator app.') }}
    </p>

    <AppTextField
      v-model="code"
      :label="t('Code')"
      inputmode="numeric"
      autocomplete="one-time-code"
      required
      autofocus
    />

    <p v-if="auth.error" class="auth-form__error" role="alert">{{ auth.error }}</p>

    <AppButton type="submit" full-width :loading="auth.busy">{{ t('Verify') }}</AppButton>

    <p v-if="byEmail && resent" class="auth-form__aside" role="status">
      {{ t('Another code is on its way. The one before it no longer works.') }}
    </p>
    <AppButton v-else-if="byEmail" variant="text" full-width :disabled="auth.busy" @click="resend">
      {{ t('Send another code') }}
    </AppButton>

    <AppButton
      v-if="canUsePasskey"
      variant="text"
      full-width
      :disabled="auth.busy"
      @click="withPasskey"
    >
      {{ t('Use a passkey instead') }}
    </AppButton>

    <AppButton
      v-if="canSwitchToEmail"
      variant="text"
      full-width
      :disabled="auth.busy"
      @click="useEmailInstead"
    >
      {{ t('Use a code by email instead') }}
    </AppButton>
  </form>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
