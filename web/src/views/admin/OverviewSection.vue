<script setup lang="ts">
/**
 * What this instance is running, and how much of everything it holds.
 *
 * The revision is the one an upgrade asks about, and reading it otherwise
 * means a shell on the server and `alembic current` — which is the whole
 * complaint `docs/motivation.md` makes about the operational view.
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import { formatBytes } from '@/formats'
import { message, usePanel } from './panel'

const { t } = useI18n()
const { failure } = usePanel()

interface Overview {
  version: string
  apiVersion: number
  revision: string | null
  database: string
  users: number
  libraries: number
  groups: number
  storagePath: string
  nominalBytes: number
  realBytes: number
  savedBytes: number
  orphanFiles: number
  missingFiles: number
}

const overview = ref<Overview | null>(null)

onMounted(async () => {
  try {
    overview.value = await request<Overview>('/web/admin/overview')
  } catch (thrown) {
    failure.value = message(thrown)
  }
})
</script>

<template>
  <div v-if="overview" class="overview">
    <section class="card">
      <h3 class="card__title">{{ t('This server') }}</h3>
      <dl class="facts">
        <dt>{{ t('altero version') }}</dt>
        <dd>{{ overview.version }}</dd>
        <dt>{{ t('Web API version') }}</dt>
        <dd>{{ overview.apiVersion }}</dd>
        <dt>{{ t('Database') }}</dt>
        <dd>{{ overview.database }}</dd>
        <!-- Named rather than described: it is what `alembic upgrade` and
             `/health` both call it, and an operator comparing two instances
             is comparing these strings. -->
        <dt>{{ t('Migration revision') }}</dt>
        <dd>{{ overview.revision ?? t('not stamped') }}</dd>
        <dt>{{ t('Attachments directory') }}</dt>
        <dd class="facts__path">{{ overview.storagePath }}</dd>
      </dl>
    </section>

    <section class="card">
      <h3 class="card__title">{{ t('What it holds') }}</h3>
      <dl class="facts">
        <dt>{{ t('Accounts') }}</dt>
        <dd>{{ overview.users }}</dd>
        <dt>{{ t('Libraries') }}</dt>
        <dd>{{ overview.libraries }}</dd>
        <dt>{{ t('Groups') }}</dt>
        <dd>{{ overview.groups }}</dd>
        <dt>{{ t('On disk') }}</dt>
        <dd>{{ formatBytes(overview.realBytes) }}</dd>
        <dt>{{ t('Saved by storing each file once') }}</dt>
        <dd>{{ formatBytes(overview.savedBytes) }}</dd>
      </dl>
      <p v-if="overview.missingFiles" class="overview__warning" role="alert">
        {{
          t('{count} attachments have no file on disk.', { count: overview.missingFiles })
        }}
      </p>
    </section>
  </div>
</template>

<style scoped>
.overview {
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

/* Two columns, the label narrow and the value taking what is left: a column
   of numbers is read down, so they line up on their own left edge. */
.facts {
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  gap: 0.35rem var(--md-spacing-4);
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.facts dt {
  color: var(--md-sys-color-on-surface-variant);
}

.facts dd {
  margin: 0;
}

.facts__path {
  overflow-wrap: anywhere;
  font-family: var(--md-sys-typescale-code-family, monospace);
}

.overview__warning {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size);
}
</style>
