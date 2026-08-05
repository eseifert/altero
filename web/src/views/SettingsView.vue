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
 * route in `router/index.ts` for why.
 */
import { computed, onMounted, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import SidebarIcon from '@/components/SidebarIcon.vue'
import KeysSection from './settings/KeysSection.vue'
import LanguageSection from './settings/LanguageSection.vue'
import ProfileSection from './settings/ProfileSection.vue'
import SecuritySection from './settings/SecuritySection.vue'
import TransferSection from './settings/TransferSection.vue'
import { providePanel } from './settings/panel'

const { t } = useI18n()

const route = useRoute()
const { notice, failure, reload } = providePanel()

/**
 * The sections, in the order the panel lists them.
 *
 * The slug is what appears in the URL and is never translated: a link somebody
 * pastes has to open the same section for the person who receives it, whatever
 * language either of them reads in.
 */
const SECTIONS: { slug: string; icon: string; label: () => string; component: Component }[] = [
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
    slug: 'import-export',
    icon: 'archive',
    label: () => t('Import and export'),
    component: TransferSection,
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
  <div class="settings">
    <aside class="settings__panel">
      <h1 class="settings__title">{{ t('Settings') }}</h1>
      <nav class="settings__sections" :aria-label="t('Settings')">
        <RouterLink
          v-for="section in SECTIONS"
          :key="section.slug"
          class="settings__section"
          :class="{ 'settings__section--current': section.slug === current.slug }"
          :aria-current="section.slug === current.slug ? 'page' : undefined"
          :to="{ name: 'settings', params: { section: section.slug } }"
        >
          <SidebarIcon :name="section.icon" />
          <span class="settings__label">{{ section.label() }}</span>
        </RouterLink>
      </nav>
    </aside>

    <section class="settings__content">
      <h2 class="settings__heading">{{ current.label() }}</h2>

      <!--
        Above the section rather than inside it: one place for "that worked"
        and "that did not", wherever on the screen the thing that failed was.
      -->
      <p v-if="notice" class="settings__notice">{{ notice }}</p>
      <p v-if="failure" class="settings__failure" role="alert">{{ failure }}</p>

      <!-- Keyed, so switching sections builds a fresh one rather than
           reusing the fields of the last: a password typed into one section's
           form has no business appearing in another's. -->
      <component :is="current.component" :key="current.slug" />
    </section>
  </div>
</template>

<style scoped>
.settings {
  display: grid;
  grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr);
  gap: var(--md-spacing-5);
  align-items: start;
}

.settings__panel {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  position: sticky;
  top: var(--md-spacing-4);
}

.settings__title {
  margin: 0;
  font-size: var(--md-sys-typescale-title-large-size, 1.35rem);
}

.settings__sections {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

/* The library sidebar's row, to the pixel: same padding, same corner, same
   fill for the current one. Two sidebars that differ slightly read as two
   applications. */
.settings__section {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  min-width: 0;
  padding: 0.35rem 0.6rem;
  border-radius: var(--md-sys-shape-corner-small);
  color: inherit;
  font-size: var(--md-sys-typescale-body-medium-size);
  text-decoration: none;
}

.settings__section:hover {
  background: var(--md-sys-color-surface-container-high);
}

.settings__section--current,
.settings__section--current:hover {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.settings__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings__content {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  min-width: 0;
  /* The cards are forms. Wider than this and a text field is a runway. */
  max-width: 34rem;
}

.settings__heading {
  margin: 0;
  font-size: var(--md-sys-typescale-title-large-size, 1.35rem);
}

.settings__notice,
.settings__failure {
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.settings__notice {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.settings__failure {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

/* Narrow enough that a column of its own would leave the forms unusable: the
   panel becomes a row of tabs above them, and stops following the scroll. */
@media (max-width: 48rem) {
  .settings {
    grid-template-columns: 1fr;
  }

  .settings__panel {
    position: static;
  }

  .settings__sections {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
</style>
