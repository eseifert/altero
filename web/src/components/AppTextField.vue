<script setup lang="ts">
import { computed, useId } from 'vue'

/**
 * A Material 3 outlined text field.
 *
 * The label is a real `<label>` bound to the input rather than a floating
 * placeholder, so it stays readable once there is text in the field and is
 * announced properly. An error message is wired up with `aria-describedby`
 * and `aria-invalid`, which is what makes the failure reach someone who
 * cannot see the red.
 */
const props = withDefaults(
  defineProps<{
    label: string
    type?: string
    autocomplete?: string
    required?: boolean
    disabled?: boolean
    error?: string | null
    hint?: string
    inputmode?: 'text' | 'numeric'
    autofocus?: boolean
  }>(),
  {
    type: 'text',
    autocomplete: undefined,
    required: false,
    disabled: false,
    error: null,
    hint: undefined,
    inputmode: undefined,
    autofocus: false,
  },
)

const model = defineModel<string>({ default: '' })

const id = useId()
const messageId = computed(() => `${id}-message`)
const message = computed(() => props.error ?? props.hint ?? null)
</script>

<template>
  <div :class="['app-field', { 'app-field--invalid': Boolean(error) }]">
    <label class="app-field__label" :for="id">{{ label }}</label>
    <input
      :id="id"
      v-model="model"
      class="app-field__input"
      :type="type"
      :autocomplete="autocomplete"
      :required="required"
      :disabled="disabled"
      :inputmode="inputmode"
      :autofocus="autofocus"
      :aria-invalid="Boolean(error)"
      :aria-describedby="message ? messageId : undefined"
    />
    <p v-if="message" :id="messageId" class="app-field__message" :role="error ? 'alert' : undefined">
      {{ message }}
    </p>
  </div>
</template>

<style scoped>
.app-field {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
}

.app-field__label {
  font-size: var(--md-sys-typescale-body-medium-size);
  line-height: var(--md-sys-typescale-body-medium-line);
  color: var(--md-sys-color-on-surface-variant);
  text-transform: none;
}

.app-field__input {
  width: 100%;
  min-height: 48px;
  padding: 0 var(--md-spacing-4);
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-extra-small);
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
  font-family: inherit;
  font-size: var(--md-sys-typescale-body-large-size);
  transition: border-color var(--md-sys-motion-duration-short) var(--md-sys-motion-easing-standard);
}

.app-field__input:focus {
  /* Two pixels of the accent, drawn inside, so the field does not shift. */
  border-color: var(--md-sys-color-primary);
  outline: 1px solid var(--md-sys-color-primary);
  outline-offset: -2px;
}

.app-field__input:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}

.app-field--invalid .app-field__input {
  border-color: var(--md-sys-color-error);
}

.app-field__message {
  margin: 0;
  font-size: var(--md-sys-typescale-body-small-size);
  line-height: var(--md-sys-typescale-body-small-line);
  color: var(--md-sys-color-on-surface-variant);
}

.app-field--invalid .app-field__message {
  color: var(--md-sys-color-error);
}
</style>
