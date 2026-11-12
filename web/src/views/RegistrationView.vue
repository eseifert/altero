<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { formatDate } from '@/formats'
import { useAuthStore } from '@/stores/auth'

interface Application { requestID: number; status: string; expires: string }
const { t } = useI18n()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const application = ref<Application | null>(null)
const proof = ref<string | null>(null)
const loading = ref(true)
const busy = ref(false)
const failure = ref<string | null>(null)
const notice = ref<string | null>(null)
const password = ref('')
const repeated = ref('')
const enrolled = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
let revision = 0
let disposed = false
const pending = computed(() => ['email_pending', 'review_pending'].includes(application.value?.status ?? ''))
const minimum = computed(() => auth.passwordMinimumLength)
const heading = computed(() => {
  if (enrolled.value) return t('Your account is ready')
  if (proof.value) return t('Confirm your email address')
  switch (application.value?.status) {
    case 'email_pending': return t('Confirm your email address')
    case 'review_pending': return t('Awaiting administrator approval')
    case 'approved': return t('Choose your password')
    case 'rejected': return t('Your request was rejected')
    case 'cancelled': return t('Your request was cancelled')
    case 'expired': return t('Your request has expired')
    default: return t('Registration request')
  }
})

async function refresh(): Promise<void> {
  const ticket = ++revision
  try {
    const result = await request<Application>('/web/registration')
    if (!disposed && ticket === revision) {
      application.value = result
      failure.value = null
    }
  } catch (thrown) {
    if (disposed || ticket !== revision) return
    if (thrown instanceof ApiError && thrown.status === 401) {
      application.value = null
      failure.value = t('This registration link is invalid or expired.')
    } else failure.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    if (!disposed) loading.value = false
  }
}

async function perform(work: () => Promise<void>): Promise<void> {
  busy.value = true
  failure.value = notice.value = null
  revision++
  try { await work() } catch (thrown) {
    failure.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally { busy.value = false; loading.value = false }
}

const confirm = () => perform(async () => {
  const token = proof.value
  proof.value = null
  await request('/web/registration/verify', { method: 'POST', body: { token } })
  await refresh()
})
const cancel = () => perform(async () => {
  await request('/web/registration/cancel', { method: 'POST' })
  await refresh()
})
const resend = () => perform(async () => {
  await request('/web/registration/resend', { method: 'POST' })
  notice.value = t('If this request can be resumed, a new link will be emailed.')
})
const enroll = () => perform(async () => {
  if (password.value !== repeated.value || password.value.length < minimum.value) return
  await request('/web/registration/enroll', { method: 'POST', body: { password: password.value } })
  password.value = repeated.value = ''
  enrolled.value = true
})
async function signIn(): Promise<void> {
  if (auth.isAuthenticated) await auth.logout()
  await router.push({ name: 'sign-in' })
}

async function captureProof(): Promise<void> {
  const token = new URLSearchParams(route.hash.replace(/^#/, '')).get('token')
  if (!token) return
  proof.value = token
  failure.value = notice.value = null
  enrolled.value = false
  revision++
  await router.replace({ path: route.path, query: route.query, hash: '' })
}
watch(() => route.hash, () => { void captureProof() })
onMounted(async () => {
  await captureProof()
  await auth.loadConfig()
  if (disposed) return
  if (proof.value) loading.value = false
  else await refresh()
  if (disposed) return
  timer = setInterval(() => {
    if (!busy.value && !proof.value && !enrolled.value && pending.value && document.visibilityState === 'visible') void refresh()
  }, 15000)
})
onUnmounted(() => { disposed = true; revision++; clearInterval(timer); proof.value = null })
</script>

<template>
  <section class="auth-form">
    <h1>{{ heading }}</h1>
    <p v-if="loading" role="status">{{ t('Loading…') }}</p>
    <p v-if="failure" class="auth-form__error" role="alert">{{ failure }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="proof">
      <p>{{ t('Confirm that you requested this account. This does not sign you in or grant library access.') }}</p>
      <AppButton :loading="busy" @click="confirm">{{ t('Confirm your email address') }}</AppButton>
    </template>
    <template v-else-if="enrolled">
      <p>{{ t('Sign in with the password you just set.') }}</p>
      <AppButton @click="signIn">{{ auth.isAuthenticated ? t('Sign out and sign in') : t('Sign in') }}</AppButton>
    </template>
    <template v-else-if="application">
      <p v-if="application.status === 'review_pending'">{{ t('An administrator must approve your request before you can use a library.') }}</p>
      <p v-if="pending">{{ t('Request deadline: {date}', { date: formatDate(application.expires) }) }}</p>
      <form v-if="application.status === 'approved' && !auth.ssoOnly" @submit.prevent="enroll">
        <AppTextField v-model="password" type="password" autocomplete="new-password" :label="t('Password')" :hint="t('At least {count} characters', { count: minimum })" required />
        <AppTextField v-model="repeated" type="password" autocomplete="new-password" :label="t('Repeat password')" required :error="repeated && repeated !== password ? t('The two passwords do not match') : null" />
        <AppButton type="submit" :loading="busy" :disabled="password.length < minimum || password !== repeated">{{ t('Set password') }}</AppButton>
      </form>
      <p v-else-if="application.status === 'approved'">{{ t('Contact the administrator to finish setting up this account.') }}</p>
      <div class="registration-actions">
        <AppButton v-if="pending" variant="text" :disabled="busy" @click="refresh">{{ t('Check status') }}</AppButton>
        <AppButton v-if="pending" variant="text" :disabled="busy" @click="cancel">{{ t('Cancel request') }}</AppButton>
        <AppButton v-if="pending || application.status === 'approved'" variant="text" :disabled="busy" @click="resend">{{ t('Send a new link') }}</AppButton>
      </div>
    </template>
    <p v-if="!proof && !loading && !enrolled" class="auth-form__aside">
      <RouterLink :to="{ name: 'register' }">{{ t('Request an account') }}</RouterLink>
      · <RouterLink :to="{ name: 'sign-in' }">{{ t('Sign in') }}</RouterLink>
    </p>
  </section>
</template>

<style scoped>
@import '@/styles/auth-form.css';
.registration-actions { display: flex; flex-wrap: wrap; gap: var(--md-spacing-2); margin-block-start: var(--md-spacing-3); }
form { display: grid; gap: var(--md-spacing-3); }
</style>
