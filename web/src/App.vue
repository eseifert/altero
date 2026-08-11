<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import ThemeMenu from '@/components/ThemeMenu.vue'
import { useAuthStore } from '@/stores/auth'
import { useGroupStore } from '@/stores/groups'
import { useNotificationStore } from '@/stores/notifications'
import { useLocaleStore } from '@/stores/locale'
import { useThemeStore } from '@/stores/theme'

const { t } = useI18n()

const auth = useAuthStore()
const theme = useThemeStore()
const locale = useLocaleStore()
const notifications = useNotificationStore()
const groups = useGroupStore()
const router = useRouter()
const route = useRoute()

/* The sign-in screens are centred on an empty page; the library gets the
   full shell with a header. Needing an account is what usually tells them
   apart, but not always: a profile page is read by strangers and is still a
   page of content, so a route can ask for the frame with `shell`. */
const bare = computed(() => route.meta.requiresAuth !== true && route.meta.shell !== true)

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
  (signedIn) => {
    if (signedIn) {
      notifications.load()
    } else {
      notifications.reset()
      groups.reset()
    }
  },
  { immediate: true },
)

async function signOut(): Promise<void> {
  await auth.logout()
  notifications.reset()
  // A list of somebody else's groups left on screen is both wrong and a small
  // disclosure, exactly as a stale notification badge would be.
  groups.reset()
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
          :to="{ name: 'groups' }"
          :aria-label="t('Groups')"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M16 19v-1.5a3 3 0 00-3-3H6a3 3 0 00-3 3V19" />
            <circle cx="9.5" cy="7.5" r="3" />
            <path d="M21 19v-1.5a3 3 0 00-2.25-2.9" />
            <path d="M15.5 4.6a3 3 0 010 5.8" />
          </svg>
        </RouterLink>
        <!-- Only for the account that administers the instance, which is
             usually nobody on a personal server. The server refuses these
             screens to everybody else regardless; this keeps a door nobody
             may open out of everybody's way. -->
        <RouterLink
          v-if="auth.user?.administrator"
          class="shell__icon"
          :to="{ name: 'admin' }"
          :aria-label="t('Administration')"
        >
          <!-- Two racked units with a light apiece, matching the sidebar's
               own `server` glyph. -->
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M5.75 5.25h12.5a1 1 0 011 1v3.5a1 1 0 01-1 1H5.75a1 1 0 01-1-1v-3.5a1 1 0 011-1z" />
            <path d="M5.75 13.25h12.5a1 1 0 011 1v3.5a1 1 0 01-1 1H5.75a1 1 0 01-1-1v-3.5a1 1 0 011-1z" />
            <path d="M8 8h.01" />
            <path d="M8 16h.01" />
          </svg>
        </RouterLink>
        <RouterLink
          v-if="auth.isAuthenticated"
          class="shell__icon"
          :to="{ name: 'settings' }"
          :aria-label="t('Settings')"
        >
          <!--
            Six teeth of radius 1.7 on a circle of radius 7.6 about (12, 12),
            joined by fillets of radius 2.7 that dip to 6.1. Every arc is a
            reflection of another in both axes, so the gear is symmetric
            whichever way you fold it. The outline reaches 9.3 and the valleys
            stop at 6.1, which puts the same white between valley and hub as
            the bell and the group icon leave between their strokes.
          -->
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M19.61 10.3A2.7 2.7 0 0 1 17.28 6.26A1.7 1.7 0 0 0 14.33 4.56A2.7 2.7 0 0 1 9.67 4.56A1.7 1.7 0 0 0 6.72 6.26A2.7 2.7 0 0 1 4.39 10.3A1.7 1.7 0 0 0 4.39 13.7A2.7 2.7 0 0 1 6.72 17.74A1.7 1.7 0 0 0 9.67 19.44A2.7 2.7 0 0 1 14.33 19.44A1.7 1.7 0 0 0 17.28 17.74A2.7 2.7 0 0 1 19.61 13.7A1.7 1.7 0 0 0 19.61 10.3Z" />
            <circle cx="12" cy="12" r="2.5" />
          </svg>
        </RouterLink>
        <ThemeMenu />
        <AppButton v-if="auth.isAuthenticated" variant="text" @click="signOut">{{ t('Sign out') }}</AppButton>
        <!-- A page with this frame that nobody is signed in for is a profile
             somebody arrived at from outside. The bar is the only chrome they
             have; without this it offers them no way in at all. -->
        <RouterLink
          v-else-if="!bare"
          class="shell__signin"
          :to="{ name: 'sign-in', query: { next: route.fullPath } }"
        >
          {{ t('Sign in') }}
        </RouterLink>
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
  background: var(--md-sys-color-surface-container);
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

/*
 * The mark rides above the line the rest of the bar is centred on.
 *
 * Only the lower half of the artwork is the name; the upper half is the A's
 * ascender, which reads as air rather than as ink. Centring the file would put
 * the word "altero" a quarter of its height below every control beside it, so
 * the whole link is lifted by that quarter -- 0.5rem at the 2rem the mark is
 * drawn -- which lands the word's own centre on the bar's. The lift is on the
 * link rather than on the image so that what is clickable is what is visible.
 */
.shell__brand {
  display: inline-flex;
  align-items: center;
  text-decoration: none;
  transform: translateY(-0.5rem);
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
/* Sized so that the name inside it is a little above the icons across the bar,
   which are drawn at 20px: the mark is the one thing in the header that is not
   a control, and it carries the name. Half of the 2rem is the ascender, which
   leaves the word itself at 1rem. */
.shell__logo {
  display: block;
  width: auto;
  height: 2rem;
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
  background: var(--md-sys-state-hover-surface);
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

.shell__signin {
  padding: 0 var(--md-spacing-3);
  color: var(--md-sys-color-primary);
  font-size: var(--md-sys-typescale-label-large-size);
  text-decoration: none;
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
