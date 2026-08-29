<script setup lang='ts'>
/**
 * The applications this account has connected, and the way to disconnect one.
 *
 * Separate from API keys next door, because they are different things and
 * saying so is the point: a key is one credential a person made and pasted
 * somewhere, and an application is somebody else's software that was granted a
 * named set of permissions. Showing them in one list would invite the reading
 * that revoking either does the same kind of thing.
 *
 * Disconnecting takes effect at once. The tokens go with the grant rather than
 * running out an hour later — a person who has decided an application should
 * stop meant now, and telling them otherwise afterwards is too late.
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import { formatDate } from '@/formats'
import { message, usePanel } from './panel'

const { t } = useI18n()

interface Authorization {
  id: number
  clientId: string
  name: string
  description: string
  scopes: string[]
  approved: string
  activeTokens: number
}

const { attempt, failure } = usePanel()

const applications = ref<Authorization[]>([])

onMounted(load)

async function load(): Promise<void> {
  try {
    applications.value = await request<Authorization[]>(
      '/web/oauth/authorizations',
    )
  } catch (thrown) {
    failure.value = message(thrown)
  }
}

/** The same sentences the consent screen used, so the two agree. */
const DESCRIPTIONS: Record<string, () => string> = {
  openid: () => t('Know who you are'),
  profile: () => t('See your name and username'),
  email: () => t('See your email address'),
  groups: () => t('See which groups you belong to'),
  'library.read': () => t('Read everything in your library'),
  'library.write': () => t('Add, change and remove things in your library'),
  'notes.read': () => t('Read your notes'),
  'files.read': () => t('Download your attachments'),
  'groups.read': () => t('Read the group libraries you belong to'),
  'groups.write': () => t('Change the group libraries you belong to'),
}

function describe(scopes: string[]): string {
  return scopes.map((scope) => DESCRIPTIONS[scope]?.() ?? scope).join(' · ')
}

const disconnect = (entry: Authorization) =>
  attempt(
    async () => {
      await request(`/web/oauth/authorizations/${entry.id}`, {
        method: 'DELETE',
      })
      await load()
    },
    t('“{name}” was disconnected and stops working immediately.', {
      name: entry.name,
    }),
  )
</script>

<template>
  <section class="card">
    <p class="settings__detail">
      {{
        t('Other applications you have allowed to reach this account. Each was given only the permissions you approved.')
      }}
    </p>

    <ul v-if="applications.length" class="settings__list">
      <li v-for="entry in applications" :key="entry.id">
        <div>
          <p class="settings__entry">{{ entry.name }}</p>
          <p v-if="entry.description" class="settings__detail">
            {{ entry.description }}
          </p>
          <p class="settings__detail">
            {{ t('Connected {when}', { when: formatDate(entry.approved) }) }}
            <template v-if="entry.activeTokens">
              · {{ t('in use now') }}</template
            >
          </p>
          <p class="settings__detail applications__grants">
            {{ describe(entry.scopes) }}
          </p>
        </div>
        <AppButton variant="text" @click="disconnect(entry)">{{
          t('Disconnect')
        }}</AppButton>
      </li>
    </ul>
    <p v-else class="settings__detail">{{ t('No applications connected.') }}</p>
  </section>
</template>

<style scoped>
@import '@/styles/settings.css';

.applications__grants {
  margin-top: var(--md-spacing-1);
}
</style>
