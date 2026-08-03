<script setup lang="ts">
import { useThemeStore, type ThemePreference } from '@/stores/theme'

const theme = useThemeStore()

const OPTIONS: Array<{ value: ThemePreference; label: string; path: string }> = [
  { value: 'light', label: 'Light', path: 'M12 5.5v-2 M12 20.5v-2 M5.5 12h-2 M20.5 12h-2 M7.3 7.3L5.9 5.9 M18.1 18.1l-1.4-1.4 M7.3 16.7l-1.4 1.4 M18.1 5.9l-1.4 1.4 M15.5 12a3.5 3.5 0 11-7 0 3.5 3.5 0 017 0z' },
  { value: 'dark', label: 'Dark', path: 'M20 13.5A8.5 8.5 0 1110.5 4a6.8 6.8 0 009.5 9.5z' },
  { value: 'system', label: 'System', path: 'M3.75 5.75h16.5v10H3.75z M8.5 19.25h7 M12 15.75v3.5' },
]
</script>

<template>
  <div class="theme-toggle" role="group" aria-label="Colour theme">
    <button
      v-for="option in OPTIONS"
      :key="option.value"
      type="button"
      class="theme-toggle__option"
      :class="{ 'theme-toggle__option--active': theme.preference === option.value }"
      :aria-pressed="theme.preference === option.value"
      :title="option.label"
      @click="theme.setPreference(option.value)"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path :d="option.path" />
      </svg>
      <span class="theme-toggle__label">{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-full);
  background: var(--md-sys-color-surface-container-low);
}

.theme-toggle__option {
  display: inline-flex;
  align-items: center;
  gap: var(--md-spacing-2);
  padding: 6px 12px;
  border: none;
  border-radius: var(--md-sys-shape-corner-full);
  background: transparent;
  color: var(--md-sys-color-on-surface-variant);
  font: inherit;
  font-size: var(--md-sys-typescale-label-medium-size);
  cursor: pointer;
}

.theme-toggle__option--active {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

/* The label is for pointer users with room; the icon carries it otherwise. */
@media (max-width: 640px) {
  .theme-toggle__label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
}
</style>
