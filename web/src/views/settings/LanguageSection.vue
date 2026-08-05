<script setup lang="ts">
/** The language the interface speaks and the zone its dates are read in. */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import { formatDateTime } from '@/formats'
import { useLocaleStore } from '@/stores/locale'
import { message, usePanel } from './panel'

const { t } = useI18n()

const locale = useLocaleStore()
const { account, busy, failure, attempt } = usePanel()

const choices = ref<{ languages: { tag: string; name: string }[]; timeZones: string[] }>({
  languages: [],
  timeZones: [],
})

/* '' is the "follow this device" option: a select cannot hold null, and the
   server reads an empty string as null for exactly this reason. */
const chosenLanguage = ref('')
const chosenTimeZone = ref('')

/** What "follow this device" resolves to here, so the option can say so. */
const automaticLanguage = computed(
  () => choices.value.languages.find((entry) => entry.tag === locale.active)?.name ?? locale.active,
)

watch(
  account,
  (loaded) => {
    if (loaded) {
      chosenLanguage.value = loaded.user.language ?? ''
      chosenTimeZone.value = loaded.user.timeZone ?? ''
    }
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    // The zone list is the server's own, so this screen cannot offer one the
    // server would then refuse.
    choices.value = await request('/web/account/locales')
  } catch (thrown) {
    failure.value = message(thrown)
  }
})

const saveLocale = () =>
  attempt(async () => {
    await request('/web/account/locale', {
      method: 'PUT',
      body: { language: chosenLanguage.value || null, timeZone: chosenTimeZone.value || null },
    })
    locale.adopt({
      language: chosenLanguage.value || null,
      timeZone: chosenTimeZone.value || null,
    })
  }, t('Language and time zone saved.'))
</script>

<template>
  <!-- One card, and the heading above it already names the section: a title
       here would be the same words twice. -->
  <section class="settings__card">
    <p class="settings__detail">
      {{ t('Both follow this device unless you choose otherwise, and travel with your account.') }}
    </p>

    <label class="settings__field">
      <span class="settings__field-label">{{ t('Language') }}</span>
      <select v-model="chosenLanguage" class="settings__select">
        <option value="">
          {{ t('Follow this device ({name})', { name: automaticLanguage }) }}
        </option>
        <option v-for="entry in choices.languages" :key="entry.tag" :value="entry.tag">
          {{ entry.name }}
        </option>
      </select>
    </label>

    <label class="settings__field">
      <span class="settings__field-label">{{ t('Time zone') }}</span>
      <select v-model="chosenTimeZone" class="settings__select">
        <option value="">
          {{ t('Follow this device ({name})', { name: locale.browserTimeZone }) }}
        </option>
        <option v-for="zone in choices.timeZones" :key="zone" :value="zone">{{ zone }}</option>
      </select>
    </label>

    <p class="settings__detail">
      {{ t('Dates look like this: {example}', { example: formatDateTime(new Date()) }) }}
    </p>

    <AppButton :loading="busy" @click="saveLocale">{{ t('Save') }}</AppButton>
  </section>
</template>

<style scoped>
@import '@/styles/settings.css';
</style>
