<script setup lang="ts">
/**
 * A Material 3 button.
 *
 * Sentence case, never uppercased -- Material 2 shouted its labels and Material
 * 3 does not, and a capitalised string is read out letter by letter by some
 * screen readers.
 */
withDefaults(
  defineProps<{
    variant?: 'filled' | 'tonal' | 'outlined' | 'text'
    type?: 'button' | 'submit'
    disabled?: boolean
    /** Shows a spinner and blocks input without changing the button's width. */
    loading?: boolean
    fullWidth?: boolean
  }>(),
  {
    variant: 'filled',
    type: 'button',
    disabled: false,
    loading: false,
    fullWidth: false,
  },
)
</script>

<template>
  <button
    :type="type"
    :class="['app-button', `app-button--${variant}`, { 'app-button--block': fullWidth }]"
    :disabled="disabled || loading"
    :aria-busy="loading"
  >
    <span v-if="loading" class="app-button__spinner" aria-hidden="true" />
    <span class="app-button__label"><slot /></span>
  </button>
</template>

<style scoped>
/* A fingertip needs about a centimetre; a pointer does not, and a taller
   button everywhere would leave the settings forms looking like a kiosk. */
@media (pointer: coarse) {
  .app-button {
    min-height: 2.75rem;
  }
}

.app-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--md-spacing-2);
  min-height: 40px;
  padding: 0 var(--md-spacing-5);
  border: none;
  border-radius: var(--md-sys-shape-corner-full);
  font-family: inherit;
  font-size: var(--md-sys-typescale-label-large-size);
  line-height: var(--md-sys-typescale-label-large-line);
  font-weight: var(--md-sys-typescale-weight-medium);
  text-transform: none;
  cursor: pointer;
  transition:
    background-color var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard),
    box-shadow var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

/* The M3 state layer: a wash of the foreground colour over the button. */
.app-button::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: currentColor;
  opacity: 0;
  transition: opacity var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
  pointer-events: none;
}

.app-button:hover:not(:disabled)::after {
  opacity: var(--md-sys-state-hover-opacity);
}

.app-button:active:not(:disabled)::after {
  opacity: var(--md-sys-state-pressed-opacity);
}

.app-button:disabled {
  cursor: not-allowed;
  opacity: 0.38;
}

.app-button--block {
  width: 100%;
}

.app-button--filled {
  background: var(--md-sys-color-primary);
  color: var(--md-sys-color-on-primary);
}

.app-button--tonal {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.app-button--outlined {
  background: transparent;
  color: var(--md-sys-color-primary);
  box-shadow: inset 0 0 0 1px var(--md-sys-color-outline);
}

.app-button--text {
  background: transparent;
  color: var(--md-sys-color-primary);
  padding: 0 var(--md-spacing-3);
}

.app-button__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: var(--md-sys-shape-corner-full);
  animation: app-button-spin 700ms linear infinite;
}

@keyframes app-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
