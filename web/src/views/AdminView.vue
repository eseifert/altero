<script setup lang="ts">
/**
 * The operator's screens.
 *
 * The one part of this interface that is about the instance rather than about
 * a library: what it is running, what it costs on disk, and the policies that
 * belong to whoever runs it. Everything here is refused by the server to
 * anybody who does not administer the instance — this view only decides
 * whether to draw it.
 *
 * Drawn by `components/SectionPanel.vue`, the same panel settings uses, so the
 * two screens read as one application.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import SectionPanel, { type PanelSection } from '@/components/SectionPanel.vue'
import AccountsSection from './admin/AccountsSection.vue'
import OverviewSection from './admin/OverviewSection.vue'
import RetentionSection from './admin/RetentionSection.vue'
import StorageSection from './admin/StorageSection.vue'
import { providePanel } from './admin/panel'

const { t } = useI18n()

const route = useRoute()
const { notice, failure } = providePanel()

/** The sections, in the order the panel lists them. */
const SECTIONS: PanelSection[] = [
  { slug: 'overview', icon: 'server', label: () => t('Overview'), component: OverviewSection },
  { slug: 'storage', icon: 'disk', label: () => t('Storage'), component: StorageSection },
  {
    slug: 'accounts',
    icon: 'accounts',
    label: () => t('Accounts'),
    component: AccountsSection,
  },
  {
    slug: 'retention',
    icon: 'retention',
    label: () => t('Retention'),
    component: RetentionSection,
  },
]

const current = computed(
  () => SECTIONS.find((section) => section.slug === route.params.section) ?? SECTIONS[0],
)
</script>

<template>
  <SectionPanel
    :title="t('Administration')"
    route-name="admin"
    :sections="SECTIONS"
    :current="current"
    :notice="notice"
    :failure="failure"
  />
</template>
