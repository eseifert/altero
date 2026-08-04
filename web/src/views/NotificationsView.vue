<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { useNotificationStore } from '@/stores/notifications'
import { formatDateTime } from '@/formats'

const { t } = useI18n()

const store = useNotificationStore()
const answering = ref<number | null>(null)

onMounted(() => store.load())

async function answer(id: number, decision: 'accept' | 'decline'): Promise<void> {
  answering.value = id
  try {
    await store.answer(id, decision)
  } catch {
    // The store holds the message; the banner below shows it.
  } finally {
    answering.value = null
  }
}

function when(iso: string): string {
  return formatDateTime(iso)
}
</script>

<template>
  <section class="notifications">
    <header class="notifications__header">
      <h1>{{ t('Notifications') }}</h1>
      <AppButton v-if="store.hasUnread" variant="text" @click="store.markAllRead()">
        {{ t('Mark all read') }}
      </AppButton>
    </header>

    <p v-if="store.error" class="notifications__error" role="alert">{{ store.error }}</p>

    <section v-if="store.invitations.length" class="notifications__group">
      <h2>{{ t('Invitations') }}</h2>
      <ul class="notifications__list">
        <li v-for="invitation in store.invitations" :key="invitation.id" class="invitation">
          <div>
            <p class="invitation__title">{{ invitation.libraryName }}</p>
            <p class="invitation__detail">
              {{
                invitation.role === 'admin'
                  ? t('{who} invited you as an administrator.', { who: invitation.invitedBy })
                  : t('{who} invited you as a member.', { who: invitation.invitedBy })
              }}
              {{ t('Expires {when}.', { when: when(invitation.expires) }) }}
            </p>
          </div>
          <div class="invitation__actions">
            <AppButton
              variant="text"
              :disabled="answering === invitation.id"
              @click="answer(invitation.id, 'decline')"
            >
              {{ t('Decline') }}
            </AppButton>
            <AppButton
              :loading="answering === invitation.id"
              @click="answer(invitation.id, 'accept')"
            >
              {{ t('Accept') }}
            </AppButton>
          </div>
        </li>
      </ul>
    </section>

    <section class="notifications__group">
      <h2 v-if="store.invitations.length">{{ t('Everything else') }}</h2>
      <p v-if="!store.notifications.length && !store.busy" class="notifications__empty">
        {{ t('Nothing to show.') }}
      </p>
      <ul v-else class="notifications__list">
        <li
          v-for="entry in store.notifications"
          :key="entry.id"
          class="notice"
          :class="{ 'notice--unread': !entry.read }"
          @click="!entry.read && store.markRead(entry.id)"
        >
          <span class="notice__dot" :aria-hidden="entry.read">
            <span v-if="!entry.read" class="visually-hidden">{{ t('Unread') }}</span>
          </span>
          <div>
            <p class="notice__subject">{{ entry.subject }}</p>
            <p v-if="entry.body" class="notice__body">{{ entry.body }}</p>
            <p class="notice__when">{{ when(entry.created) }}</p>
          </div>
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.notifications {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-5);
}

.notifications__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.notifications__group h2 {
  margin: 0 0 var(--md-spacing-3);
  font-size: var(--md-sys-typescale-title-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
  color: var(--md-sys-color-on-surface-variant);
}

.notifications__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

.notifications__empty,
.notifications__error {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.notifications__error {
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

.invitation {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-4);
  padding: var(--md-spacing-4);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
}

.invitation__title {
  margin: 0;
  font-size: var(--md-sys-typescale-title-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.invitation__detail,
.notice__body,
.notice__when {
  margin: var(--md-spacing-1) 0 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.invitation__actions {
  display: flex;
  gap: var(--md-spacing-2);
  flex: none;
}

.notice {
  display: flex;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
}

.notice--unread {
  background: var(--md-sys-color-surface-container-low);
  cursor: pointer;
}

.notice__dot {
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: var(--md-sys-shape-corner-full);
  flex: none;
  background: transparent;
}

.notice--unread .notice__dot {
  background: var(--md-sys-color-primary);
}

.notice__subject {
  margin: 0;
}

.notice__when {
  font-size: var(--md-sys-typescale-body-small-size);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}
</style>
