<script setup lang="ts">
/**
 * The accounts on this instance, and what can be done about them.
 *
 * Making one for somebody else, resetting a password, suspending and deleting
 * are the operations `docs/motivation.md` names as the reason an instance is
 * "something a systems administrator runs rather than a librarian". They are
 * still `altero user …` on the command line; this is the same work without a
 * shell.
 *
 * Each of them asks for the administrator's own password, as everything that
 * touches a credential does, and the server asks again.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { formatDate } from '@/formats'
import { message, usePanel } from './panel'

const { t } = useI18n()
const { busy, failure, attempt } = usePanel()

interface Account {
  id: number
  username: string
  displayName: string
  email: string | null
  emailVerified: boolean
  administrator: boolean
  disabled: boolean
  disabledAt: string | null
  keys: number
  groups: number
}

const accounts = ref<Account[]>([])

/** The account a row's controls are open for, or null. */
const chosen = ref<Account | null>(null)
/** The administrator's own password, asked for once per action. */
const password = ref('')
/** A new account being made, or null while the form is closed. */
const draft = ref<{ username: string; displayName: string; email: string; password: string } | null>(
  null,
)
/** The password of an account just made, shown once and then forgotten. */
const issued = ref<{ username: string; password: string } | null>(null)
/** A password being set for somebody else. */
const replacement = ref('')

const sorted = computed(() => [...accounts.value].sort((a, b) => a.id - b.id))

async function reload(): Promise<void> {
  accounts.value = (await request<{ users: Account[] }>('/web/admin/users')).users
}

onMounted(async () => {
  try {
    await reload()
  } catch (thrown) {
    failure.value = message(thrown)
  }
})

function open(account: Account): void {
  chosen.value = chosen.value?.id === account.id ? null : account
  password.value = ''
  replacement.value = ''
}

function startDraft(): void {
  draft.value = { username: '', displayName: '', email: '', password: '' }
  issued.value = null
  password.value = ''
}

const create = () =>
  attempt(async () => {
    const wanted = draft.value
    if (!wanted) return
    await request('/web/admin/users', {
      method: 'POST',
      body: { ...wanted, currentPassword: password.value },
    })
    // Held on screen until this section is left: it is the only time anybody
    // sees it, exactly as an API key is shown once.
    issued.value = { username: wanted.username, password: wanted.password }
    draft.value = null
    password.value = ''
    await reload()
  }, t('Account created.'))

const change = (account: Account, body: Record<string, unknown>, success: string) =>
  attempt(async () => {
    await request(`/web/admin/users/${account.id}`, {
      method: 'PATCH',
      body: { ...body, currentPassword: password.value },
    })
    await reload()
    chosen.value = accounts.value.find((entry) => entry.id === account.id) ?? null
  }, success)

const setPassword = (account: Account) =>
  attempt(async () => {
    await request(`/web/admin/users/${account.id}/password`, {
      method: 'POST',
      body: { password: replacement.value, currentPassword: password.value },
    })
    replacement.value = ''
  }, t('Password set. Their other browsers were signed out.'))

/** A link the account sets its own password from, so no password is dictated. */
const link = ref<{ username: string; link: string; sent: boolean; hours: number } | null>(null)

const sendLink = (account: Account) =>
  attempt(async () => {
    const issued = await request<{ link: string; sent: boolean; hours: number }>(
      `/web/admin/users/${account.id}/reset`,
      { method: 'POST', body: { currentPassword: password.value } },
    )
    link.value = { username: account.username, ...issued }
  }, t('Link issued.'))

const revoke = (account: Account) =>
  attempt(async () => {
    await request(`/web/admin/users/${account.id}/revoke`, {
      method: 'POST',
      body: { currentPassword: password.value },
    })
    await reload()
  }, t('Credentials revoked.'))

const remove = (account: Account) =>
  attempt(async () => {
    await request(`/web/admin/users/${account.id}`, {
      method: 'DELETE',
      body: { currentPassword: password.value },
    })
    chosen.value = null
    await reload()
  }, t('Account deleted.'))
</script>

<template>
  <div class="accounts">
    <section class="card">
      <div class="accounts__heading">
        <h3 class="card__title">{{ t('Accounts') }}</h3>
        <AppButton variant="text" :disabled="busy" @click="startDraft">
          {{ t('Create account') }}
        </AppButton>
      </div>

      <!-- Shown once and never again, like an API key. -->
      <p v-if="issued" class="card__inset" role="status">
        {{ t('The password for {username} is {password}. Copy this now. It will not be shown again.', { username: issued.username, password: issued.password }) }}
      </p>

      <form v-if="draft" class="accounts__form" @submit.prevent="create">
        <AppTextField v-model="draft.username" :label="t('Username')" autocomplete="off" />
        <AppTextField v-model="draft.displayName" :label="t('Display name')" autocomplete="off" />
        <AppTextField
          v-model="draft.email"
          :label="t('Email address (optional)')"
          autocomplete="off"
        />
        <AppTextField
          v-model="draft.password"
          type="password"
          :label="t('Password for the new account')"
          autocomplete="new-password"
        />
        <AppTextField
          v-model="password"
          type="password"
          :label="t('Your password')"
          autocomplete="current-password"
        />
        <div class="accounts__actions">
          <AppButton type="submit" :disabled="busy">{{ t('Create') }}</AppButton>
          <AppButton variant="text" :disabled="busy" @click="draft = null">
            {{ t('Cancel') }}
          </AppButton>
        </div>
      </form>

      <ul class="accounts__list">
        <li v-for="account in sorted" :key="account.id" class="accounts__entry">
          <button class="accounts__row" type="button" @click="open(account)">
            <span class="accounts__name">
              {{ account.displayName || account.username }}
              <span class="accounts__username">{{ account.username }}</span>
            </span>
            <span class="accounts__marks">
              <span v-if="account.administrator" class="chip">
                {{ t('Administrator') }}
              </span>
              <span v-if="account.disabled" class="chip chip--warning">
                {{ t('Suspended') }}
              </span>
            </span>
          </button>

          <div v-if="chosen?.id === account.id" class="accounts__detail">
            <dl class="facts">
              <dt>{{ t('Email') }}</dt>
              <dd>{{ account.email || '—' }}</dd>
              <dt>{{ t('API keys') }}</dt>
              <dd>{{ account.keys }}</dd>
              <dt>{{ t('Groups') }}</dt>
              <dd>{{ account.groups }}</dd>
              <template v-if="account.disabledAt">
                <dt>{{ t('Suspended') }}</dt>
                <dd>{{ formatDate(account.disabledAt) }}</dd>
              </template>
            </dl>

            <AppTextField
              v-model="password"
              type="password"
              :label="t('Your password')"
              :hint="t('Everything below asks for it, as your own settings do.')"
              autocomplete="current-password"
            />

            <div class="accounts__actions">
              <AppButton
                variant="text"
                :disabled="busy || !password"
                @click="change(account, { disabled: !account.disabled }, account.disabled ? t('Back in service.') : t('Suspended. Their libraries are untouched.'))"
              >
                {{ account.disabled ? t('Reinstate') : t('Suspend') }}
              </AppButton>
              <AppButton
                variant="text"
                :disabled="busy || !password"
                @click="change(account, { administrator: !account.administrator }, t('Saved.'))"
              >
                {{ account.administrator ? t('Stop administering') : t('Make administrator') }}
              </AppButton>
              <AppButton variant="text" :disabled="busy || !password" @click="revoke(account)">
                {{ t('Revoke keys and sessions') }}
              </AppButton>
              <AppButton variant="text" :disabled="busy || !password" @click="sendLink(account)">
                {{ t('Send a password link') }}
              </AppButton>
              <AppButton variant="text" :disabled="busy || !password" @click="remove(account)">
                {{ t('Delete account') }}
              </AppButton>
            </div>

            <div class="accounts__actions">
              <AppTextField
                v-model="replacement"
                type="password"
                :label="t('New password for this account')"
                autocomplete="new-password"
              />
              <AppButton
                variant="text"
                :disabled="busy || !password || !replacement"
                @click="setPassword(account)"
              >
                {{ t('Set password') }}
              </AppButton>
            </div>

            <p v-if="link && link.username === account.username" class="card__inset">
              <template v-if="link.sent">
                {{ t('A link was emailed to them. It is good for {hours} hours and can be used once.', { hours: link.hours }) }}
              </template>
              <template v-else>
                {{ t('Give them this link. It is good for {hours} hours and can be used once.', { hours: link.hours }) }}
              </template>
              <span class="accounts__link">{{ link.link }}</span>
            </p>

            <p class="card__note">
              {{ t('Suspending stops both credentials — the API key a Zotero client holds and this interface — and touches nothing they own. Deleting removes their library and everything in it, and cannot be undone.') }}
            </p>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
@import '@/styles/surfaces.css';

.accounts {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
}


.accounts__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-2);
}


.accounts__form,
.accounts__detail {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
}

.accounts__list {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.accounts__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-3);
  width: 100%;
  padding: 0.45rem 0.6rem;
  border: none;
  border-radius: var(--md-sys-shape-corner-small);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.accounts__row:hover {
  background: var(--md-sys-state-hover-surface);
}

.accounts__name {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.accounts__username {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}

.accounts__marks {
  display: flex;
  gap: var(--md-spacing-2);
  flex: none;
}

.accounts__detail {
  padding: var(--md-spacing-3) 0.6rem var(--md-spacing-4);
}

.accounts__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--md-spacing-2);
}

.accounts__link {
  display: block;
  margin-top: var(--md-spacing-2);
  font-family: var(--md-sys-typescale-code-family, monospace);
  overflow-wrap: anywhere;
}


.facts {
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  gap: 0.35rem var(--md-spacing-4);
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.facts dt {
  color: var(--md-sys-color-on-surface-variant);
}

.facts dd {
  margin: 0;
}
</style>
