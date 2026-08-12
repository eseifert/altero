<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import * as passkeys from '@/passkeys'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')

/* Offered only where the instance can hold one and the browser can make one.
   A button that always failed would be worse than no button. */
const canUsePasskey = computed(() => auth.passkeysAvailable && passkeys.available())
const passkeyBusy = ref(false)
const passkeyError = ref<string | null>(null)

async function withPasskey(): Promise<void> {
  passkeyBusy.value = true
  passkeyError.value = null
  try {
    await auth.signInWithPasskey()
  } catch (thrown) {
    // A cancelled prompt is not a failure to report: they closed it.
    if (!(thrown instanceof passkeys.Cancelled)) {
      passkeyError.value = thrown instanceof Error ? thrown.message : String(thrown)
    }
    return
  } finally {
    passkeyBusy.value = false
  }
  await router.push((route.query.next as string) || { name: 'library' })
}

/* Why a federated sign-in came back without signing anybody in. The server
   redirects here with a slug rather than a sentence, because the sentence
   belongs in the reader's own language and the server does not know it. What
   the directory itself said is deliberately not passed on: that text is
   written for whoever configured the client. */
const REASONS: Record<string, () => string> = {
  refused: () => t('That sign-in was not completed.'),
  expired: () => t('That sign-in took too long. Please try again.'),
  'not-permitted': () => t('Your account there is not permitted to use this server.'),
  'unknown-provider': () => t('That way of signing in is not available here.'),
  'provider-disabled': () => t('That way of signing in is not available here.'),
  'provider-unreachable': () => t('That provider could not be reached. Try again shortly.'),
  'not-signed-in': () => t('Please sign in first.'),
}

const failure = computed(() => {
  const named = route.query.error
  return typeof named === 'string' ? (REASONS[named]?.() ?? REASONS.refused()) : null
})

/* A plain link rather than a fetch: the server answers with a redirect to the
   directory, and the browser's own navigation is what has to carry it. */
function ssoHref(slug: string): string {
  const next = typeof route.query.next === 'string' ? route.query.next : '/library'
  return `/web/auth/sso/${encodeURIComponent(slug)}/start?next=${encodeURIComponent(next)}`
}

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
    <h1>{{ t('Sign in') }}</h1>
    <p class="auth-form__lead">{{ t('to your altero library') }}</p>

    <p v-if="failure || passkeyError" class="auth-form__error" role="alert">
      {{ failure ?? passkeyError }}
    </p>

    <AppButton
      v-if="canUsePasskey"
      variant="outlined"
      full-width
      :loading="passkeyBusy"
      @click="withPasskey"
    >
      {{ t('Sign in with a passkey') }}
    </AppButton>

    <template v-if="auth.providers.length || canUsePasskey">
      <a
        v-for="provider in auth.providers"
        :key="provider.slug"
        class="auth-form__provider"
        :href="ssoHref(provider.slug)"
      >
        {{ t('Continue with {provider}', { provider: provider.displayName }) }}
      </a>
      <p class="auth-form__divider"><span>{{ t('or') }}</span></p>
    </template>

    <AppTextField
      v-model="username"
      :label="t('Username')"
      autocomplete="username"
      required
      autofocus
    />
    <AppTextField
      v-model="password"
      :label="t('Password')"
      type="password"
      autocomplete="current-password"
      required
    />

    <p v-if="auth.error" class="auth-form__error" role="alert">{{ auth.error }}</p>

    <AppButton type="submit" full-width :loading="auth.busy">{{ t('Sign in') }}</AppButton>

    <p v-if="auth.passwordResetOpen" class="auth-form__aside">
      <RouterLink :to="{ name: 'forgot-password' }">{{ t('Forgotten password?') }}</RouterLink>
    </p>

    <p v-if="auth.registrationOpen" class="auth-form__aside">
      {{ t('No account yet?') }}
      <RouterLink :to="{ name: 'register' }">{{ t('Create one') }}</RouterLink>
    </p>
  </form>
</template>

<style scoped>
@import '@/styles/auth-form.css';

/* Shaped like an outlined AppButton rather than being one: this is a
   navigation to another origin, and an anchor is what a browser expects to
   hand a redirect to. */
.auth-form__provider {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 var(--md-spacing-5);
  border-radius: var(--md-sys-shape-corner-full);
  box-shadow: inset 0 0 0 1px var(--md-sys-color-outline);
  color: var(--md-sys-color-primary);
  font-size: var(--md-sys-typescale-label-large-size);
  font-weight: var(--md-sys-typescale-weight-medium);
  text-decoration: none;
}

/* A fingertip needs about a centimetre, as AppButton says. */
@media (pointer: coarse) {
  .auth-form__provider {
    min-height: 2.75rem;
  }
}

.auth-form__provider:hover {
  background: color-mix(in srgb, currentColor 8%, transparent);
}

.auth-form__divider {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-3);
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}

.auth-form__divider::before,
.auth-form__divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--md-sys-color-outline-variant);
}
</style>
