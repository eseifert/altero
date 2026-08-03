<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'

interface LinkRequest {
  status: string
  requestedUserId: number | null
  expiresInSeconds: number
  canApprove: boolean
  reason: string | null
}

const auth = useAuthStore()
const route = useRoute()

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))

const details = ref<LinkRequest | null>(null)
const password = ref('')
const state = ref<'loading' | 'asking' | 'approved' | 'declined' | 'failed'>('loading')
const failure = ref<string | null>(null)
const busy = ref(false)

onMounted(async () => {
  if (!token.value) {
    failure.value = 'That link is missing its request token.'
    state.value = 'failed'
    return
  }
  try {
    details.value = await request<LinkRequest>(`/web/link/${encodeURIComponent(token.value)}`)
    state.value = 'asking'
  } catch (thrown) {
    failure.value =
      thrown instanceof ApiError && thrown.status === 404
        ? 'That request has expired or does not exist. Start the sign-in again in Zotero.'
        : message(thrown)
    state.value = 'failed'
  }
})

function message(thrown: unknown): string {
  return thrown instanceof Error ? thrown.message : String(thrown)
}

async function approve(): Promise<void> {
  busy.value = true
  failure.value = null
  try {
    await request(`/web/link/${encodeURIComponent(token.value)}/approve`, {
      method: 'POST',
      body: { currentPassword: password.value },
    })
    state.value = 'approved'
  } catch (thrown) {
    failure.value = message(thrown)
  } finally {
    password.value = ''
    busy.value = false
  }
}

async function decline(): Promise<void> {
  busy.value = true
  try {
    await request(`/web/link/${encodeURIComponent(token.value)}/deny`, { method: 'POST' })
    state.value = 'declined'
  } catch (thrown) {
    failure.value = message(thrown)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="auth-form">
    <h1>Connect Zotero</h1>

    <p v-if="state === 'loading'" class="auth-form__lead">Checking the request…</p>

    <template v-else-if="state === 'approved'">
      <p class="auth-form__lead">
        Done. Zotero is picking up the connection now — you can close this page and go back to
        it.
      </p>
      <AppButton full-width @click="$router.push({ name: 'library' })">
        Go to your library
      </AppButton>
    </template>

    <template v-else-if="state === 'declined'">
      <p class="auth-form__lead">Refused. Zotero has been told to stop waiting.</p>
      <AppButton variant="text" full-width @click="$router.push({ name: 'library' })">
        Go to your library
      </AppButton>
    </template>

    <template v-else-if="state === 'failed'">
      <p class="auth-form__error" role="alert">{{ failure }}</p>
    </template>

    <template v-else-if="details && !details.canApprove">
      <p class="auth-form__error" role="alert">{{ details.reason }}</p>
      <AppButton variant="text" full-width @click="$router.push({ name: 'library' })">
        Go to your library
      </AppButton>
    </template>

    <template v-else>
      <p class="auth-form__lead">
        A Zotero client is asking to connect to
        <strong>{{ auth.user?.username }}</strong
        >.
      </p>

      <!-- Said plainly, because it is a bigger grant than it looks: the key
           outlives this browser session and cannot be scoped down later. -->
      <ul class="link__grants">
        <li>Read and change everything in your library</li>
        <li>Read and change any group library you belong to</li>
        <li>Download and upload attachments</li>
      </ul>
      <p class="link__note">
        This creates a key that keeps working until you remove it in Settings, even after you
        sign out here.
      </p>

      <AppTextField
        v-model="password"
        label="Confirm your password"
        type="password"
        autocomplete="current-password"
        required
        autofocus
      />

      <p v-if="failure" class="auth-form__error" role="alert">{{ failure }}</p>

      <AppButton type="button" full-width :loading="busy" @click="approve">Connect</AppButton>
      <AppButton variant="text" full-width :disabled="busy" @click="decline">
        Not now
      </AppButton>
    </template>
  </section>
</template>

<style scoped>
@import '@/styles/auth-form.css';

.link__grants {
  margin: 0;
  padding-left: var(--md-spacing-5);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
}

.link__note {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}
</style>
