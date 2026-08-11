<script setup lang="ts">
/**
 * How long this server keeps what nobody asked it to keep.
 *
 * zotero.org empties the trash after thirty days; here that is the operator's
 * own number, and it starts at never — an instance that began deleting
 * somebody's trash because it was upgraded would be a surprise of the worst
 * kind.
 *
 * Which is also why the preview is next to the button rather than behind it:
 * a period is a decision about deleting other people's work, and seeing what
 * it would take before it takes it is what makes setting one safe.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { message, usePanel } from './panel'

const { t } = useI18n()
const { busy, failure, attempt } = usePanel()

interface SettingsPayload {
  settings: Record<string, number>
  defaults: Record<string, number>
  limits: Record<string, { maximum: number; zero: string }>
}

interface SweepReport {
  preview: boolean
  itemsDeleted: number
  libraries: number
  activity: number
  uploads: number
  sessions: number
  verifications: number
  invitations: number
  summary: string
}

const payload = ref<SettingsPayload | null>(null)
const form = ref<Record<string, string>>({})
const report = ref<SweepReport | null>(null)

/** The periods, in the order the screen asks about them. */
const FIELDS = [
  {
    name: 'trashRetentionDays',
    label: () => t('Days an item stays in the trash'),
    hint: () =>
      t('Zero keeps the trash for good, which is what this server does until you say otherwise. zotero.org uses 30.'),
  },
  {
    name: 'activityRetentionDays',
    label: () => t('Days a delivered group activity record is kept'),
    hint: () =>
      t('What group notifications were sent from. Nobody is notified twice, and this only decides how long the record stays.'),
  },
  {
    name: 'uploadRetentionHours',
    label: () => t('Hours an unfinished upload is remembered'),
    hint: () => t('A file the client asked to send and never sent. Nothing is lost: it asks again.'),
  },
]

function load(data: SettingsPayload): void {
  payload.value = data
  form.value = Object.fromEntries(
    Object.entries(data.settings).map(([name, value]) => [name, String(value)]),
  )
}

/** Whether a field holds something the server would refuse anyway.
 *
 * `String` because Vue hands back a number for an input of type `number` and
 * an empty string for an empty one, and this has to answer for both. */
function invalid(name: string): boolean {
  const raw = String(form.value[name] ?? '')
  const value = Number(raw)
  const maximum = payload.value?.limits[name]?.maximum ?? 0
  return raw.trim() === '' || !Number.isInteger(value) || value < 0 || value > maximum
}

const unusable = computed(() => FIELDS.some((field) => invalid(field.name)))

/** Why a field would be refused, said before the server has to say it. */
function refusal(name: string): string {
  return t('A whole number of periods, from 0 to {maximum}.', {
    maximum: payload.value?.limits[name]?.maximum ?? 0,
  })
}

onMounted(async () => {
  try {
    load(await request<SettingsPayload>('/web/admin/settings'))
  } catch (thrown) {
    failure.value = message(thrown)
  }
})

const save = () =>
  attempt(async () => {
    const body = Object.fromEntries(
      Object.entries(form.value).map(([name, value]) => [name, Number(value)]),
    )
    load(await request<SettingsPayload>('/web/admin/settings', { method: 'PUT', body }))
    report.value = null
  }, t('Saved.'))

/**
 * What a sweep did, in this reader's language.
 *
 * Built here rather than shown as the server's own sentence: that one is
 * written for a log and for the shell, and both are English. What crosses the
 * wire is numbers.
 */
const outcome = computed(() => {
  const done = report.value
  if (!done) return []
  return [
    { count: done.itemsDeleted, text: () => t('{count} items out of the trash', { count: done.itemsDeleted }) },
    { count: done.activity, text: () => t('{count} delivered activity records', { count: done.activity }) },
    { count: done.uploads, text: () => t('{count} unfinished uploads', { count: done.uploads }) },
    { count: done.sessions, text: () => t('{count} expired sessions', { count: done.sessions }) },
    { count: done.verifications, text: () => t('{count} expired confirmation links', { count: done.verifications }) },
    { count: done.invitations, text: () => t('{count} expired invitations', { count: done.invitations }) },
  ].filter((entry) => entry.count > 0)
})

/** `preview` decides whether this is a rehearsal or the thing itself. */
function sweep(preview: boolean) {
  return attempt(
    async () => {
      report.value = await request<SweepReport>(
        `/web/admin/retention/run?preview=${preview}`,
        { method: 'POST' },
      )
    },
    preview ? t('Checked.') : t('Deleted.'),
  )
}
</script>

<template>
  <div v-if="payload" class="retention">
    <section class="card">
      <h3 class="card__title">{{ t('How long things are kept') }}</h3>

      <AppTextField
        v-for="field in FIELDS"
        :key="field.name"
        v-model="form[field.name]"
        type="number"
        inputmode="numeric"
        :label="field.label()"
        :hint="field.hint()"
        :error="invalid(field.name) ? refusal(field.name) : null"
      />

      <div class="retention__actions">
        <AppButton :disabled="busy || unusable" @click="save">{{ t('Save') }}</AppButton>
      </div>
    </section>

    <section class="card">
      <h3 class="card__title">{{ t('Apply them now') }}</h3>
      <p class="retention__hint">
        {{
          t(
            'Deleting an item out of the trash is a write like any other: the library takes a new version and every client learns what went. There is no undo.',
          )
        }}
      </p>
      <div class="retention__actions">
        <AppButton variant="text" :disabled="busy" @click="sweep(true)">
          {{ t('See what would go') }}
        </AppButton>
        <AppButton :disabled="busy" @click="sweep(false)">{{ t('Delete it now') }}</AppButton>
      </div>
      <p v-if="report" class="retention__report" role="status">
        <template v-if="outcome.length">
          {{ report.preview ? t('Would delete:') : t('Deleted:') }}
          {{ outcome.map((entry) => entry.text()).join(', ') }}
        </template>
        <template v-else>{{ t('Nothing to delete.') }}</template>
      </p>
    </section>
  </div>
</template>

<style scoped>
.retention {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
}

.card {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container);
}

.card__title {
  margin: 0;
  font-size: var(--md-sys-typescale-title-medium-size, 1.1rem);
}

.retention__hint {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}

.retention__actions {
  display: flex;
  gap: var(--md-spacing-2);
  align-items: center;
}

.retention__report {
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}
</style>
