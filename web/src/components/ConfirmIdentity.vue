<script setup lang="ts">
/**
 * Proving, just before something that hands out a credential, that whoever is
 * at the browser is the account holder.
 *
 * A password is one way and, for an account the directory created, not one
 * there is: such an account proves itself by going back through the
 * directory, which then sends the browser back to this page. The server says
 * which of the two the account has (`/web/account/proof`) and whether the
 * browser proved itself in the last few minutes, in which case nothing is
 * asked at all. See `services/reauth.py`.
 *
 * `ready` says whether the form holding this can be sent; `refresh` asks again
 * after a refusal, since a proof can lapse while the page stands open.
 */
import { computed, onMounted, ref, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'
import AppTextField from '@/components/AppTextField.vue'

interface Proof {
  password: boolean
  fresh: boolean
  providers: { slug: string; displayName: string }[]
}

const { t } = useI18n()
const route = useRoute()

const password = defineModel<string>({ default: '' })
const ready = defineModel<boolean>('ready', { default: false })

const proof = ref<Proof | null>(null)

async function refresh(): Promise<void> {
  try {
    proof.value = await request<Proof>('/web/account/proof')
  } catch {
    // Asking for a password is what these pages did before they could ask,
    // and the server says so if that was wrong.
    proof.value = { password: true, fresh: false, providers: [] }
  }
}

onMounted(refresh)
defineExpose({ refresh })

watchEffect(() => {
  const known = proof.value
  ready.value = known !== null && (known.fresh || (known.password && password.value !== ''))
})

const nothingToOffer = computed(
  () =>
    proof.value !== null &&
    !proof.value.fresh &&
    !proof.value.password &&
    !proof.value.providers.length,
)

/* A navigation rather than a fetch: the directory has to see the browser, and
   sends it back to this very page. */
const reauthHref = (slug: string) =>
  `/web/auth/sso/${encodeURIComponent(slug)}/start?purpose=reauth&next=${encodeURIComponent(route.fullPath)}`
</script>

<template>
  <template v-if="proof">
    <p v-if="proof.fresh" class="auth-form__aside">{{ t('You have just confirmed it is you.') }}</p>

    <template v-else>
      <AppTextField
        v-if="proof.password"
        v-model="password"
        :label="t('Confirm your password')"
        type="password"
        autocomplete="current-password"
        required
        autofocus
      />
      <p v-else-if="proof.providers.length" class="auth-form__aside">
        {{ t('Confirm it is you by signing in again.') }}
      </p>

      <a
        v-for="provider in proof.providers"
        :key="provider.slug"
        class="auth-form__provider"
        :href="reauthHref(provider.slug)"
      >
        {{ t('Confirm with {provider}', { provider: provider.displayName }) }}
      </a>

      <p v-if="nothingToOffer" class="auth-form__error" role="alert">
        {{
          t(
            'This account has no password and no sign-in service to confirm it is you with. An administrator can set a password for it.',
          )
        }}
      </p>
    </template>
  </template>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
