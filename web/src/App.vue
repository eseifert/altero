<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import ThemeMenu from '@/components/ThemeMenu.vue'
import { useAuthStore } from '@/stores/auth'
import { useNotificationStore } from '@/stores/notifications'
import { useLocaleStore } from '@/stores/locale'
import { useThemeStore } from '@/stores/theme'

const { t } = useI18n()

const auth = useAuthStore()
const theme = useThemeStore()
const locale = useLocaleStore()
const notifications = useNotificationStore()
const router = useRouter()
const route = useRoute()

/* The sign-in screens are centred on an empty page; the library gets the
   full shell with a header. */
const bare = computed(() => route.meta.requiresAuth !== true)

/* Reading text wants a narrow measure; browsing a library wants room. The
   library is three panes side by side, and at the reading width the middle one
   is left with a few characters of title. */
const wide = computed(() => route.name === 'library')

/* Verification gates notifications and nothing else, so this is a reminder
   rather than a wall. */
const unconfirmed = computed(
  () => auth.isAuthenticated && auth.user?.email !== null && !auth.user?.emailVerified,
)

onMounted(() => {
  theme.initialise()
  // Before anything is drawn: the browser's language and zone are what every
  // screen falls back to until the account says otherwise.
  locale.initialise()
  auth.loadConfig()
})

/* Loaded once signed in, and again whenever that changes: a badge left over
   from the previous account would be both wrong and a small disclosure. */
watch(
  () => auth.isAuthenticated,
  (signedIn) => (signedIn ? notifications.load() : notifications.reset()),
  { immediate: true },
)

async function signOut(): Promise<void> {
  await auth.logout()
  notifications.reset()
  await router.push({ name: 'sign-in' })
}
</script>

<template>
  <div class="shell" :class="{ 'shell--bare': bare, 'shell--wide': wide }">
    <a class="skip-link" href="#content">{{ t('Skip to content') }}</a>

    <header class="shell__bar">
      <!--
        Two files, one for each scheme, because the mark is drawn in the teal
        of the palette it sits in. Which one shows is decided in CSS rather
        than here: the theme store only stamps the root once Vue has mounted,
        and a logo chosen in script would be the light one for a frame on a
        dark screen. The link is named once, on itself, so it reads as one
        thing however many images CSS is showing.
      -->
      <RouterLink class="shell__brand" :to="{ name: 'library' }" aria-label="altero">
        <img class="shell__logo shell__logo--light" src="@/assets/logo-light.svg" alt="" />
        <img class="shell__logo shell__logo--dark" src="@/assets/logo-dark.svg" alt="" />
      </RouterLink>

      <div class="shell__actions">
        <RouterLink
          v-if="auth.isAuthenticated"
          class="shell__icon"
          :to="{ name: 'notifications' }"
          :aria-label="
            notifications.unread
              ? t('Notifications, {count} unread', { count: notifications.unread })
              : t('Notifications')
          "
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M18 8.5a6 6 0 10-12 0c0 6-2.25 7.5-2.25 7.5h16.5S18 14.5 18 8.5z" />
            <path d="M13.75 19.5a2 2 0 01-3.5 0" />
          </svg>
          <span v-if="notifications.hasUnread" class="shell__badge">
            {{ notifications.unread > 9 ? '9+' : notifications.unread }}
          </span>
        </RouterLink>
        <RouterLink
          v-if="auth.isAuthenticated"
          class="shell__icon"
          :to="{ name: 'settings' }"
          :aria-label="t('Settings')"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M14.5 12a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z" />
            <path d="M19.4 14a1.7 1.7 0 00.34 1.87l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.7 1.7 0 00-1.87-.34 1.7 1.7 0 00-1 1.56V20a2 2 0 11-4 0v-.09a1.7 1.7 0 00-1.1-1.56 1.7 1.7 0 00-1.87.34l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.7 1.7 0 00.34-1.87 1.7 1.7 0 00-1.56-1H4a2 2 0 110-4h.09a1.7 1.7 0 001.56-1.1 1.7 1.7 0 00-.34-1.87l-.06-.06a2 2 0 112.83-2.83l.06.06a1.7 1.7 0 001.87.34H10a1.7 1.7 0 001-1.56V4a2 2 0 114 0v.09a1.7 1.7 0 001 1.56 1.7 1.7 0 001.87-.34l.06-.06a2 2 0 112.83 2.83l-.06.06a1.7 1.7 0 00-.34 1.87V10a1.7 1.7 0 001.56 1H20a2 2 0 110 4h-.09a1.7 1.7 0 00-1.56 1z" />
          </svg>
        </RouterLink>
        <ThemeMenu />
        <AppButton v-if="auth.isAuthenticated" variant="text" @click="signOut">{{ t('Sign out') }}</AppButton>
      </div>
    </header>

    <p v-if="unconfirmed" class="shell__notice" role="status">
      <span>
        <i18n-t keypath="Confirm {address} to receive security notifications and invitations. Your library works either way.">
          <template #address><strong>{{ auth.user?.email }}</strong></template>
        </i18n-t>
      </span>
      <AppButton variant="text" @click="auth.resendVerification()">{{ t('Resend') }}</AppButton>
    </p>

    <!-- `tabindex="-1"` so the skip link can put focus here; without it the
         browser scrolls to the landmark and leaves focus in the header. -->
    <main id="content" class="shell__main" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

/*
 * A bar set slightly back from the page, the way GitHub's is: a tinted surface
 * and a hairline underneath, rather than the page colour running edge to edge
 * with only a rule to say where the chrome stops. It stays put when the library
 * scrolls, since that is where sign-out and settings live.
 */
.shell__bar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-4);
  padding: var(--md-spacing-2) var(--md-spacing-5);
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
  background: var(--md-sys-color-surface-container-low);
}

/* The sign-in screens are one card on an empty page; a bar of chrome above it
   would be furniture around nothing. */
.shell--bare .shell__bar {
  position: static;
  border-bottom: none;
  background: none;
}

.shell__main:focus {
  outline: none;
}

.shell__brand {
  display: inline-flex;
  align-items: center;
  text-decoration: none;
}

/*
 * The logo, in whichever scheme is on screen.
 *
 * The same order the tokens use: the system's preference decides it, and
 * `data-theme` from the theme store overrides that in either direction. Both
 * halves are written out for each theme, so an explicit light choice on a dark
 * desktop hides the dark mark rather than merely showing the light one over
 * it.
 */
.shell__logo {
  display: block;
  width: auto;
  height: 1.1rem;
}

.shell__logo--dark {
  display: none;
}

@media (prefers-color-scheme: dark) {
  .shell__logo--light {
    display: none;
  }

  .shell__logo--dark {
    display: block;
  }
}

:root[data-theme='light'] .shell__logo--light,
:root[data-theme='dark'] .shell__logo--dark {
  display: block;
}

:root[data-theme='light'] .shell__logo--dark,
:root[data-theme='dark'] .shell__logo--light {
  display: none;
}

.shell__icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--md-sys-shape-corner-full);
  color: var(--md-sys-color-on-surface-variant);
}

.shell__icon:hover {
  background: var(--md-sys-color-surface-container-high);
}

.shell__badge {
  position: absolute;
  top: 4px;
  right: 2px;
  min-width: 16px;
  padding: 0 4px;
  border-radius: var(--md-sys-shape-corner-full);
  background: var(--md-sys-color-primary);
  color: var(--md-sys-color-on-primary);
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}

.shell__actions {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-1);
}

.shell__notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-3);
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-5);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.shell__main {
  flex: 1;
  width: 100%;
  max-width: 64rem;
  margin: 0 auto;
  padding: var(--md-spacing-6) var(--md-spacing-5);
}

/* Still bounded: a table stretched across an ultrawide display is no easier to
   read than a cramped one. */
.shell--wide .shell__main {
  max-width: 110rem;
}

/* The auth screens hold a single narrow column, centred across the page. */
.shell--bare .shell__notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-3);
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-5);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  font-size: var(--md-sys-typescale-body-medium-size);
}

/*
 * Centred across, never down the page. This rule lost its `.shell--bare`
 * prefix at some point and so applied everywhere, which made the main area a
 * flex container that shrank to its contents and re-centred them: selecting a
 * library or opening the detail pane moved every row and button under the
 * pointer. Vertical centring did the same on any page whose height changed.
 */
.shell--bare .shell__main {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: var(--md-spacing-7);
}
</style>
