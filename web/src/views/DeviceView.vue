<script setup lang="ts">
/**
 * Where somebody types the code a device is showing them.
 *
 * The whole of the device flow's own interface, and deliberately almost
 * nothing: what a code resolves to is an ordinary pending authorization, so
 * from here the browser goes to the same consent screen every other
 * application gets. A second consent screen written for devices would be a
 * second place for the two to disagree about what is being granted.
 *
 * `/device/done` is the other half — where the consent screen sends somebody
 * afterwards, since a device has no address to be returned to and is sitting
 * there polling.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const code = ref('')
const failure = ref<string | null>(null)
const busy = ref(false)

/** True on `/device/done`, which says the device may be picked up again. */
const answered = computed(() => route.path.endsWith('/done'))

onMounted(() => {
  /* `verification_uri_complete` carries the code, so a device that can show a
     link or a QR code spares somebody the typing. It is only ever a
     convenience: nothing is submitted until they press the button, because
     approving is theirs to do. */
  if (typeof route.query.code === 'string') {
    code.value = route.query.code
  }
})

function message(thrown: unknown): string {
  return thrown instanceof Error ? thrown.message : String(thrown)
}

async function submit(): Promise<void> {
  if (!code.value.trim() || busy.value) {
    return
  }
  busy.value = true
  failure.value = null
  try {
    const { handle } = await request<{ handle: string }>('/web/oauth/device', {
      method: 'POST',
      body: { userCode: code.value.trim() },
    })
    await router.push({ name: 'authorize', query: { request: handle } })
  } catch (thrown) {
    failure.value = message(thrown)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="auth-form">
    <template v-if="answered">
      <h1>{{ t('Device connected') }}</h1>
      <p class="auth-form__lead">
        {{ t('You can go back to your device now.') }}
      </p>
      <AppButton variant="text" full-width @click="$router.push({ name: 'library' })">
        {{ t('Go to your library') }}
      </AppButton>
    </template>

    <template v-else>
      <h1>{{ t('Connect a device') }}</h1>
      <p class="auth-form__lead">
        {{ t('Enter the code shown on your device.') }}
      </p>

      <AppTextField
        v-model="code"
        :label="t('Code')"
        autocomplete="off"
        autocapitalize="characters"
        spellcheck="false"
        required
        autofocus
        @keyup.enter="submit"
      />

      <p v-if="failure" class="auth-form__error" role="alert">{{ failure }}</p>

      <AppButton type="button" full-width :loading="busy" @click="submit">
        {{ t('Continue') }}
      </AppButton>
    </template>
  </section>
</template>

<style scoped>
@import '@/styles/auth-form.css';
</style>
