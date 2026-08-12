<script setup lang="ts">
/**
 * The directories this instance accepts a sign-in from.
 *
 * Two things on this screen exist because of specific ways it goes wrong.
 *
 * The **callback address** is shown rather than left to be worked out, and is
 * the first field: a redirect URI that does not match the one registered at
 * the directory is refused outright, with an error page nobody here can act
 * on. Where `ALTERO_PUBLIC_URL` is unset the address is built from whatever
 * request arrived, which behind a proxy is the proxy's idea of it — so the
 * screen says that too.
 *
 * The **client secret** is write-only. The server never returns it, so the
 * field is left empty and saving without touching it keeps what is stored.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { formatDate } from '@/formats'
import { usePanel } from './panel'

const { t } = useI18n()

const { busy, notice, failure, attempt } = usePanel()

interface Provider {
  id: number
  slug: string
  kind: string
  displayName: string
  enabled: boolean
  issuer: string
  clientId: string
  hasClientSecret: boolean
  scopes: string
  usernameClaim: string
  nameClaim: string
  emailClaim: string
  createAccounts: boolean
  requiredClaim: string
  requiredValue: string
  revokeKeysOnLoss: boolean
  discovered: string | null
  redirectUri: string
}

const providers = ref<Provider[]>([])
const publicUrlConfigured = ref(true)

/** The one being edited, or a blank one being added. */
const editing = ref<Partial<Provider> | null>(null)
const secret = ref('')
const adminPassword = ref('')
const warning = ref<string | null>(null)

function message(thrown: unknown): string {
  return thrown instanceof ApiError ? thrown.message : String(thrown)
}

async function load(): Promise<void> {
  const body = await request<{ providers: Provider[]; publicUrlConfigured: boolean }>(
    '/web/admin/providers',
  )
  providers.value = body.providers
  publicUrlConfigured.value = body.publicUrlConfigured
}

onMounted(async () => {
  try {
    await load()
  } catch (thrown) {
    failure.value = message(thrown)
  }
})

const isNew = computed(() => editing.value !== null && !editing.value.id)

function add(): void {
  editing.value = {
    kind: 'oidc',
    enabled: true,
    scopes: 'profile email',
    usernameClaim: 'preferred_username',
    nameClaim: 'name',
    emailClaim: 'email',
    createAccounts: false,
  }
  secret.value = ''
  warning.value = null
}

function edit(provider: Provider): void {
  editing.value = { ...provider }
  secret.value = ''
  warning.value = null
}

function cancel(): void {
  editing.value = null
  secret.value = ''
  adminPassword.value = ''
}

const save = () =>
  attempt(async () => {
    const draft = editing.value
    if (!draft) return

    const body: Record<string, unknown> = {
      displayName: draft.displayName ?? '',
      enabled: draft.enabled ?? true,
      issuer: draft.issuer ?? '',
      clientId: draft.clientId ?? '',
      scopes: draft.scopes ?? '',
      usernameClaim: draft.usernameClaim ?? '',
      nameClaim: draft.nameClaim ?? '',
      emailClaim: draft.emailClaim ?? '',
      createAccounts: draft.createAccounts ?? false,
      requiredClaim: draft.requiredClaim ?? '',
      requiredValue: draft.requiredValue ?? '',
      revokeKeysOnLoss: draft.revokeKeysOnLoss ?? false,
      currentPassword: adminPassword.value,
    }
    // Left out entirely when untouched, which is what keeps the stored one.
    if (secret.value) body.clientSecret = secret.value

    const answer = draft.id
      ? await request<{ warning: string | null }>(`/web/admin/providers/${draft.slug}`, {
          method: 'PATCH',
          body,
        })
      : await request<{ warning: string | null }>('/web/admin/providers', {
          method: 'POST',
          body: { ...body, slug: draft.slug, kind: draft.kind },
        })

    warning.value = answer.warning
    await load()
    editing.value = null
    secret.value = ''
    adminPassword.value = ''
  }, t('Saved.'))

const remove = (provider: Provider) =>
  attempt(async () => {
    await request(`/web/admin/providers/${provider.slug}`, {
      method: 'DELETE',
      body: { currentPassword: adminPassword.value },
    })
    adminPassword.value = ''
    await load()
  }, t('That provider was removed.'))
</script>

<template>
  <section v-if="!publicUrlConfigured" class="card">
    <p class="settings__detail">
      {{
        t(
          'ALTERO_PUBLIC_URL is not set, so the callback address below is built from whatever request arrived — behind a proxy that is the proxy’s idea of it. Set it before configuring a provider.',
        )
      }}
    </p>
  </section>

  <section v-if="warning" class="card">
    <p class="settings__detail" role="alert">{{ warning }}</p>
  </section>

  <section v-for="provider in providers" :key="provider.id" class="card">
    <h2 class="card__title">
      {{ provider.displayName || provider.slug }}
      <span v-if="!provider.enabled" class="chip">{{ t('Off') }}</span>
    </h2>
    <p class="settings__detail">{{ provider.issuer }}</p>
    <p class="settings__detail">
      <template v-if="provider.discovered">
        {{ t('Configuration read {when}', { when: formatDate(provider.discovered) }) }}
      </template>
      <template v-else>{{ t('Configuration not read yet') }}</template>
    </p>
    <p class="settings__detail">{{ t('Callback address') }}</p>
    <code class="card__inset settings__secret">{{ provider.redirectUri }}</code>
    <div class="settings__field">
      <AppButton variant="tonal" :loading="busy" @click="edit(provider)">
        {{ t('Change') }}
      </AppButton>
    </div>
  </section>

  <section v-if="editing" class="card">
    <h2 class="card__title">{{ isNew ? t('Add a provider') : t('Change this provider') }}</h2>

    <AppTextField
      v-if="isNew"
      v-model="editing.slug as string"
      :label="t('Short name')"
      :hint="t('Appears in the sign-in address. Lower-case letters, digits and hyphens.')"
    />
    <AppTextField v-model="editing.displayName as string" :label="t('Name on the button')" />
    <AppTextField
      v-model="editing.issuer as string"
      :label="t('Issuer')"
      :hint="t('The base URL. Its configuration is read from /.well-known/openid-configuration.')"
    />
    <AppTextField v-model="editing.clientId as string" :label="t('Client ID')" />
    <AppTextField
      v-model="secret"
      type="password"
      :label="t('Client secret')"
      autocomplete="new-password"
      :hint="
        editing.hasClientSecret
          ? t('One is stored. Leave this empty to keep it.')
          : t('Never shown again once saved.')
      "
    />
    <AppTextField v-model="editing.scopes as string" :label="t('Scopes')" />
    <AppTextField v-model="editing.usernameClaim as string" :label="t('Username claim')" />
    <AppTextField v-model="editing.nameClaim as string" :label="t('Display name claim')" />
    <AppTextField v-model="editing.emailClaim as string" :label="t('Email claim')" />

    <label class="settings__check">
      <input v-model="editing.createAccounts" type="checkbox" />
      {{ t('Make an account for anyone who signs in this way') }}
    </label>

    <AppTextField
      v-model="editing.requiredClaim as string"
      :label="t('Required claim')"
      :hint="t('Leave empty to let anyone at the provider sign in. Checked at every sign-in.')"
    />
    <AppTextField v-model="editing.requiredValue as string" :label="t('Required value')" />

    <label class="settings__check">
      <input v-model="editing.revokeKeysOnLoss" type="checkbox" />
      {{ t('Also revoke API keys when somebody loses the required claim') }}
    </label>

    <label class="settings__check">
      <input v-model="editing.enabled" type="checkbox" />
      {{ t('Offer this on the sign-in page') }}
    </label>

    <AppTextField
      v-model="adminPassword"
      type="password"
      :label="t('Your password')"
      autocomplete="current-password"
    />

    <div class="settings__field">
      <AppButton :loading="busy" @click="save">{{ t('Save') }}</AppButton>
      <AppButton variant="text" @click="cancel">{{ t('Cancel') }}</AppButton>
      <AppButton
        v-if="!isNew"
        variant="outlined"
        :loading="busy"
        @click="remove(editing as Provider)"
      >
        {{ t('Remove') }}
      </AppButton>
    </div>
    <p v-if="!isNew" class="settings__detail">
      {{ t('Removing it also removes every account’s connection to it.') }}
    </p>
  </section>

  <section v-if="!editing" class="card">
    <AppButton variant="tonal" @click="add">{{ t('Add a provider') }}</AppButton>
    <p v-if="!providers.length" class="settings__detail">
      {{ t('Nobody can sign in through another service until one is configured here.') }}
    </p>
  </section>

  <p v-if="notice" class="settings__detail" role="status">{{ notice }}</p>
</template>

<style scoped>
@import '@/styles/settings.css';
</style>
