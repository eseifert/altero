<script setup lang="ts">
/**
 * A screen made of sections, with a panel down the side.
 *
 * Settings and the administration screens are the same shape — a list of
 * sections, one showing, one place at the top where whichever section
 * succeeded or failed says so — and they are two sidebars in one application,
 * so they are drawn by one component rather than by two that agree today.
 *
 * Which section is showing lives in the URL rather than in a ref, so a link
 * can point at one and the back button walks them; the owning view resolves
 * it and hands it over, along with the route name its links are built from.
 */
import type { Component } from 'vue'

import SidebarIcon from '@/components/SidebarIcon.vue'

export interface PanelSection {
  /** What appears in the URL. Never translated: a pasted link has to open the
   *  same section for whoever receives it, in whatever language they read. */
  slug: string
  icon: string
  label: () => string
  component: Component
}

defineProps<{
  title: string
  /** The named route whose `section` parameter these links set. */
  routeName: string
  sections: PanelSection[]
  current: PanelSection
  notice?: string | null
  failure?: string | null
}>()
</script>

<template>
  <div class="section-panel">
    <aside class="section-panel__panel">
      <h1 class="section-panel__title">{{ title }}</h1>
      <nav class="section-panel__sections" :aria-label="title">
        <RouterLink
          v-for="section in sections"
          :key="section.slug"
          class="section-panel__section"
          :class="{ 'section-panel__section--current': section.slug === current.slug }"
          :aria-current="section.slug === current.slug ? 'page' : undefined"
          :to="{ name: routeName, params: { section: section.slug } }"
        >
          <SidebarIcon :name="section.icon" />
          <span class="section-panel__label">{{ section.label() }}</span>
        </RouterLink>
      </nav>
    </aside>

    <section class="section-panel__content">
      <h2 class="section-panel__heading">{{ current.label() }}</h2>

      <!--
        Above the section rather than inside it: one place for "that worked"
        and "that did not", wherever on the screen the thing that failed was.
      -->
      <p v-if="notice" class="section-panel__notice">{{ notice }}</p>
      <p v-if="failure" class="section-panel__failure" role="alert">{{ failure }}</p>

      <!-- Keyed, so switching sections builds a fresh one rather than
           reusing the fields of the last: a password typed into one section's
           form has no business appearing in another's. -->
      <component :is="current.component" :key="current.slug" />
    </section>
  </div>
</template>

<style scoped>
.section-panel {
  display: grid;
  grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr);
  gap: var(--md-spacing-5);
  align-items: start;
}

.section-panel__panel {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  position: sticky;
  top: var(--md-spacing-4);
}

.section-panel__title {
  margin: 0;
  font-size: var(--md-sys-typescale-title-large-size, 1.35rem);
}

.section-panel__sections {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

/* The library sidebar's row, to the pixel: same padding, same corner, same
   fill for the current one. Two sidebars that differ slightly read as two
   applications. */
.section-panel__section {
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

.section-panel__section:hover {
  background: var(--md-sys-state-hover-surface);
}

.section-panel__section--current,
.section-panel__section--current:hover {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.section-panel__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.section-panel__content {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
  min-width: 0;
  /* The cards are forms. Wider than this and a text field is a runway. */
  max-width: 34rem;
}

.section-panel__heading {
  margin: 0;
  font-size: var(--md-sys-typescale-title-large-size, 1.35rem);
}

.section-panel__notice,
.section-panel__failure {
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.section-panel__notice {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.section-panel__failure {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

/* Narrow enough that a column of its own would leave the forms unusable: the
   panel becomes a row of tabs above them, and stops following the scroll. */
@media (max-width: 48rem) {
  .section-panel {
    grid-template-columns: 1fr;
  }

  .section-panel__panel {
    position: static;
  }

  .section-panel__sections {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
</style>
