<script setup lang="ts">
/**
 * Settings, as a side panel and one section at a time.
 *
 * It used to be every card on one page, which meant scrolling past the
 * authenticator and eight API keys to reach the time zone. The sections are
 * the same cards, grouped by the question they answer, and the panel is the
 * library's: the same rows, the same current-row fill, so the two screens read
 * as one application.
 *
 * Which section is showing lives in the URL rather than in a ref — see the
 * route in `router/index.ts` for why. The panel itself is
 * `components/SectionPanel.vue`, shared with the administration screens.
 */
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import SectionPanel, { type PanelSection } from '@/components/SectionPanel.vue'
import ApplicationsSection from './settings/ApplicationsSection.vue'
import KeysSection from './settings/KeysSection.vue'
import LanguageSection from './settings/LanguageSection.vue'
import MigrateSection from './settings/MigrateSection.vue'
import ProfileSection from './settings/ProfileSection.vue'
import SecuritySection from './settings/SecuritySection.vue'
import TransferSection from './settings/TransferSection.vue'
import { providePanel } from './settings/panel'

const { t } = useI18n()

const route = useRoute()
const { notice, failure, reload } = providePanel()

/** The sections, in the order the panel lists them. */
const SECTIONS: PanelSection[] = [
  { slug: 'profile', icon: 'account', label: () => t('Profile'), component: ProfileSection },
  {
    slug: 'security',
    icon: 'security',
    label: () => t('Sign-in and security'),
    component: SecuritySection,
  },
  {
    slug: 'language',
    icon: 'language',
    label: () => t('Language and time zone'),
    component: LanguageSection,
  },
  { slug: 'keys', icon: 'keys', label: () => t('API keys'), component: KeysSection },
  {
    slug: 'applications',
    icon: 'providers',
    label: () => t('Connected applications'),
    component: ApplicationsSection,
  },
  {
    slug: 'import-export',
    icon: 'archive',
    label: () => t('Import and export'),
    component: TransferSection,
  },
  {
    slug: 'migrate',
    icon: 'archive',
    label: () => t('Move from zotero.org'),
    component: MigrateSection,
  },
]

/* An unknown slug falls back to the first section rather than showing an empty
   page: settings is reached from a header icon, and landing on nothing there
   leaves no way to tell a typo from a broken build. */
const current = computed(
  () => SECTIONS.find((section) => section.slug === route.params.section) ?? SECTIONS[0],
)

onMounted(reload)
</script>

<template>
  <SectionPanel
    :title="t('Settings')"
    route-name="settings"
    :sections="SECTIONS"
    :current="current"
    :notice="notice"
    :failure="failure"
  />
</template>
