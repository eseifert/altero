<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/stores/auth'
import { useNotificationStore } from '@/stores/notifications'
import { formatDate } from '@/formats'

/**
 * Where an emailed invitation lands.
 *
 * The token in the link is the whole credential for *reading* the invitation,
 * which is why this screen works signed out: somebody who has no account here
 * yet has to be able to see what they were asked to join before deciding to
 * make one. Answering it still needs a session, and the server still checks
 * that the address it was sent to is the one answering — holding the link is
 * not the same as being the person it was offered to.
 */

interface Invitation {
  id: number
  libraryName: string
  email: string
  role: 'member' | 'admin'
  status: string
  expires: string
  invitedBy: string
  hasAccount: boolean
}

const { t } = useI18n()

const auth = useAuthStore()
const notifications = useNotificationStore()
const route = useRoute()
const router = useRouter()

const token = computed(() => String(route.query.token ?? ''))
const invitation = ref<Invitation | null>(null)
const failure = ref<string | null>(null)
const done = ref<string | null>(null)
const busy = ref(false)

onMounted(load)

async function load(): Promise<void> {
  if (!token.value) {
    failure.value = t('That link is missing its token.')
    return
  }
  try {
    invitation.value = await request<Invitation>(
      `/web/invitations/token/${encodeURIComponent(token.value)}`,
    )
  } catch (thrown) {
    failure.value = thrown instanceof ApiError ? thrown.message : String(thrown)
  }
}

async function answer(decision: 'accept' | 'decline'): Promise<void> {
  busy.value = true
  failure.value = null
  try {
    await request(`/web/invitations/token/${encodeURIComponent(token.value)}/${decision}`, {
      method: 'POST',
    })
    done.value = decision === 'accept' ? t('You have joined the group.') : t('Invitation declined.')
    // The badge counts this invitation until it is answered.
    await notifications.load()
    if (decision === 'accept') {
      await router.push({ name: 'groups' })
    }
  } catch (thrown) {
    failure.value = thrown instanceof ApiError ? thrown.message : String(thrown)
  } finally {
    busy.value = false
  }
}

/* Signing in or registering has to come back here, so the invitation can be
   answered rather than left in an inbox nobody looks at twice. */
const next = computed(() => ({ query: { next: route.fullPath } }))
</script>

<template>
  <section class="invitation">
    <h1>{{ t('An invitation') }}</h1>

    <p v-if="failure" class="invitation__error" role="alert">{{ failure }}</p>
    <p v-else-if="done" class="invitation__notice" role="status">{{ done }}</p>

    <template v-if="invitation && !done">
      <p>
        {{
          invitation.role === 'admin'
            ? t('{who} invited you to “{name}” as an administrator.', {
                who: invitation.invitedBy,
                name: invitation.libraryName,
              })
            : t('{who} invited you to “{name}” as a member.', {
                who: invitation.invitedBy,
                name: invitation.libraryName,
              })
        }}
      </p>
      <p class="invitation__detail">
        {{ t('Sent to {address}.', { address: invitation.email }) }}
        {{ t('Expires {when}.', { when: formatDate(invitation.expires) }) }}
      </p>

      <p v-if="invitation.status !== 'pending'" class="invitation__detail">
        {{ t('That invitation has already been answered.') }}
      </p>

      <template v-else-if="auth.isAuthenticated">
        <div class="invitation__actions">
          <AppButton variant="text" :disabled="busy" @click="answer('decline')">
            {{ t('Decline') }}
          </AppButton>
          <AppButton :loading="busy" @click="answer('accept')">{{ t('Accept') }}</AppButton>
        </div>
      </template>

      <template v-else>
        <p class="invitation__detail">
          {{
            invitation.hasAccount
              ? t('Sign in to answer it.')
              : t('Make an account with this address to answer it.')
          }}
        </p>
        <div class="invitation__actions">
          <RouterLink v-if="invitation.hasAccount" :to="{ name: 'sign-in', ...next }">
            <AppButton>{{ t('Sign in') }}</AppButton>
          </RouterLink>
          <RouterLink v-else :to="{ name: 'register', ...next }">
            <AppButton>{{ t('Create account') }}</AppButton>
          </RouterLink>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.invitation {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  max-width: 32rem;
  padding: var(--md-spacing-6);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
}

.invitation h1 {
  margin: 0;
  font-size: var(--md-sys-typescale-headline-small-size);
}

.invitation p {
  margin: 0;
}

.invitation__detail {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.invitation__error,
.invitation__notice {
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.invitation__error {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

.invitation__notice {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.invitation__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--md-spacing-2);
  margin-top: var(--md-spacing-3);
}

.invitation__actions a {
  text-decoration: none;
}
</style>
