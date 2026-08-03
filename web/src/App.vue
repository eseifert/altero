<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const auth = useAuthStore()
const theme = useThemeStore()
const router = useRouter()
const route = useRoute()

/* The sign-in screens are centred on an empty page; the library gets the
   full shell with a header. */
const bare = computed(() => route.meta.requiresAuth !== true)

onMounted(() => {
  theme.initialise()
  auth.loadConfig()
})

async function signOut(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'sign-in' })
}
</script>

<template>
  <div class="shell" :class="{ 'shell--bare': bare }">
    <header class="shell__bar">
      <RouterLink class="shell__brand" :to="{ name: 'library' }">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 3.75h11.5a2 2 0 012 2v14.5H7a2 2 0 01-2-2z" />
          <path d="M7 20.25a2 2 0 010-4h11.5" />
        </svg>
        <span>altero</span>
      </RouterLink>

      <div class="shell__actions">
        <ThemeToggle />
        <AppButton v-if="auth.isAuthenticated" variant="text" @click="signOut">Sign out</AppButton>
      </div>
    </header>

    <main class="shell__main">
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

.shell__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-4);
  padding: var(--md-spacing-3) var(--md-spacing-5);
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
}

.shell--bare .shell__bar {
  border-bottom: none;
}

.shell__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--md-spacing-2);
  color: var(--md-sys-color-primary);
  font-size: var(--md-sys-typescale-title-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
  text-decoration: none;
}

.shell__actions {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-3);
}

.shell__main {
  flex: 1;
  width: 100%;
  max-width: 64rem;
  margin: 0 auto;
  padding: var(--md-spacing-6) var(--md-spacing-5);
}

/* The auth screens centre their single column instead. */
.shell--bare .shell__main {
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: var(--md-spacing-7);
}
</style>
