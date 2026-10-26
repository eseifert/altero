<script setup lang="ts">
/**
 * Where the toasts appear: along the bottom edge, above everything else.
 *
 * One live region for all of them, polite, so a screen reader says each
 * message once it is done with what it was saying rather than interrupting.
 * The region is always in the page; one that appears with its first message is
 * one some readers never announce.
 */
import { useI18n } from 'vue-i18n'

import AppIcon from '@/components/AppIcon.vue'
import { useToastStore } from '@/stores/toasts'

const { t } = useI18n()
const store = useToastStore()
</script>

<template>
  <div class="toasts" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="toast in store.toasts"
        :key="toast.id"
        class="toast"
        @pointerenter="store.hold(toast.id)"
        @pointerleave="store.release(toast.id)"
        @focusin="store.hold(toast.id)"
        @focusout="store.release(toast.id)"
      >
        <p class="toast__message">{{ toast.message }}</p>
        <button
          v-if="toast.action"
          class="toast__action"
          type="button"
          @click="store.act(toast.id)"
        >
          {{ toast.action.label }}
        </button>
        <button
          class="toast__dismiss"
          type="button"
          :aria-label="t('Dismiss')"
          @click="store.dismiss(toast.id)"
        >
          <AppIcon name="close" :size="18" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  inset-inline: 0;
  inset-block-end: max(var(--md-spacing-4), env(safe-area-inset-bottom));
  z-index: 100;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--md-spacing-2);
  padding-inline: var(--md-spacing-4);
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  inline-size: min(100%, 560px);
  min-block-size: 48px;
  padding-block: var(--md-spacing-1);
  padding-inline: var(--md-spacing-4) var(--md-spacing-1);
  border-radius: 4px;
  background: var(--md-sys-color-inverse-surface);
  color: var(--md-sys-color-inverse-on-surface);
  box-shadow: var(--md-sys-elevation-3);
  pointer-events: auto;
}

.toast__message {
  flex: 1;
  margin: 0;
  padding-block: var(--md-spacing-2);
}

.toast__action {
  min-block-size: 40px;
  padding-inline: var(--md-spacing-3);
  border: 0;
  border-radius: 20px;
  background: transparent;
  color: var(--md-sys-color-inverse-primary);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.toast__action:hover {
  background: color-mix(in srgb, var(--md-sys-color-inverse-primary) 12%, transparent);
}

.toast__dismiss {
  display: grid;
  flex: none;
  place-items: center;
  inline-size: 40px;
  block-size: 40px;
  padding: 0;
  border: 0;
  border-radius: var(--md-sys-shape-corner-full);
  background: none;
  color: var(--md-sys-color-inverse-on-surface);
  cursor: pointer;
}

.toast__dismiss:hover {
  background: color-mix(in srgb, var(--md-sys-color-inverse-on-surface) 12%, transparent);
}

/* The ring the rest of the interface draws is for its own surfaces; on the
   inverse one it would barely show. */
.toast__action:focus-visible,
.toast__dismiss:focus-visible {
  outline: 2px solid var(--md-sys-color-inverse-primary);
  outline-offset: 2px;
}
</style>
