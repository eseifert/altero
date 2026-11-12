<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { ApiError, request } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()

const auth = useAuthStore()
const minimumPasswordLength = computed(() => auth.passwordMinimumLength)
const gated = computed(() => auth.registrationApproval && !auth.firstAccount)
const applying = ref(false)
const applied = ref(false)
const failure = ref<string | null>(null)
const router = useRouter()
const route = useRoute()

/* Where to go once the account exists. Ordinarily the library; when an emailed
   invitation sent them here, back to it, so the thing they came to answer is
   the next thing they see rather than something to find again in an inbox. */
const next = computed(() => (route.query.next as string) || { name: 'library' })

/* Three ways to be looking at this form, and they are three different
   sentences: an invitation brought you, the instance has nobody in it yet, or
   the deployment leaves registration open. */
const lead = computed(() => {
  if (route.query.next) {
    return t('Use the address the invitation was sent to, and you will be able to answer it.')
  }
  return auth.firstAccount
    ? t('This instance has no accounts yet, so this one will be yours.')
    : t('Registration is open on this server.')
})

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
  () => touched.value && password.value.length > 0 && password.value.length < minimumPasswordLength.value,
)
const submittable = computed(
  () => gated.value || (password.value.length >= minimumPasswordLength.value && password.value === repeated.value),
)

async function submit(): Promise<void> {
  touched.value = true
  if (!submittable.value) {
    return
  }
  if (gated.value) {
    applying.value = true
    failure.value = null
    try {
      await request('/web/registration/apply', { method: 'POST', body: {
        username: username.value, email: email.value, displayName: displayName.value,
      } })
      applied.value = true
    } catch (thrown) {
      failure.value = thrown instanceof ApiError ? thrown.message : String(thrown)
    } finally {
      applying.value = false
    }
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
  await router.push(next.value)
}
</script>

<template>
  <section v-if="applied" class="auth-form">
    <h1>{{ t('Check your email') }}</h1>
    <p role="status">{{ t('If these details can be used, an email will explain the next step.') }}</p>
    <p>{{ t('If no message arrives, wait a minute and submit the same details again.') }}</p>
    <AppButton variant="text" @click="applied = false">{{ t('Back') }}</AppButton>
  </section>
  <form v-else class="auth-form" @submit.prevent="submit">
    <h1>{{ gated ? t('Request an account') : t('Create your account') }}</h1>
    <p class="auth-form__lead">
      {{ lead }}
    </p>
    <p v-if="gated">{{ t('Your email must be verified and an administrator must approve the request.') }}</p>
    <p v-if="gated && auth.registrationDomains.length">{{ t('Allowed email domains: {domains}', { domains: auth.registrationDomains.join(', ') }) }}</p>

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
      v-if="!gated"
      v-model="password"
      :label="t('Password')"
      type="password"
      autocomplete="new-password"
      required
      :hint="t('At least {count} characters', { count: minimumPasswordLength })"
      :error="
        tooShort ? t('A password must be at least {count} characters', { count: minimumPasswordLength }) : null
      "
    />
    <AppTextField
      v-if="!gated"
      v-model="repeated"
      :label="t('Repeat password')"
      type="password"
      autocomplete="new-password"
      required
      :error="mismatch ? t('The two passwords do not match') : null"
    />

    <p v-if="failure || (!gated && auth.error)" class="auth-form__error" role="alert">{{ failure || auth.error }}</p>

    <AppButton type="submit" full-width :loading="auth.busy || applying">{{ gated ? t('Request an account') : t('Create account') }}</AppButton>

    <p class="auth-form__aside">
      {{ t('Already have an account?') }}
      <RouterLink :to="{ name: 'sign-in', query: route.query }">{{ t('Sign in') }}</RouterLink>
    </p>
  </form>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
