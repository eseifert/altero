<script setup lang="ts">
/**
 * What each library costs, and what does not add up.
 *
 * Two totals rather than one. Files are stored once per digest, so a paper
 * attached in a group and in somebody's own library is on disk once and in
 * both libraries' accounts: what a library costs on its own is the number to
 * ask a group about, and what is on disk is the number to buy. zotero.org
 * cannot tell them apart, which is what the storage-quota threads on the
 * forums are about.
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '@/api/client'
import { formatBytes } from '@/formats'
import { message, usePanel } from './panel'

const { t } = useI18n()
const { failure } = usePanel()

interface LibraryUsage {
  id: number
  type: string
  ownerId: number
  name: string
  version: number
  items: number
  trashed: number
  collections: number
  tags: number
  attachments: number
  files: number
  bytes: number
  missing: number
}

interface StorageReport {
  libraries: LibraryUsage[]
  nominalBytes: number
  realBytes: number
  savedBytes: number
  storedFiles: number
  storedBytes: number
  orphanFiles: number
  orphanBytes: number
  missingFiles: number
}

const report = ref<StorageReport | null>(null)

/** How a library is addressed in the API, which is how an operator acts on it. */
function address(library: LibraryUsage): string {
  return `${library.type}/${library.ownerId}`
}

onMounted(async () => {
  try {
    report.value = await request<StorageReport>('/web/admin/storage')
  } catch (thrown) {
    failure.value = message(thrown)
  }
})
</script>

<template>
  <div v-if="report" class="storage">
    <section class="card">
      <h3 class="card__title">{{ t('Across the instance') }}</h3>
      <dl class="facts">
        <dt>{{ t('On disk') }}</dt>
        <dd>{{ formatBytes(report.storedBytes) }}</dd>
        <dt>{{ t('Counted across libraries') }}</dt>
        <dd>{{ formatBytes(report.nominalBytes) }}</dd>
        <dt>{{ t('Saved by storing each file once') }}</dt>
        <dd>{{ formatBytes(report.savedBytes) }}</dd>
      </dl>
      <p class="storage__note">
        {{
          t(
            'A file attached in two libraries is stored once and counted in both. The first number is what this server has to hold; the second is what the libraries would cost apart.',
          )
        }}
      </p>
      <p v-if="report.orphanFiles" class="storage__note">
        {{
          t('{count} files are no longer referenced by any library, holding {size}.', {
            count: report.orphanFiles,
            size: formatBytes(report.orphanBytes),
          })
        }}
      </p>
      <p v-if="report.missingFiles" class="storage__warning" role="alert">
        {{ t('{count} attachments have no file on disk.', { count: report.missingFiles }) }}
      </p>
    </section>

    <section class="card">
      <h3 class="card__title">{{ t('By library') }}</h3>
      <!-- Its own scroller: a table of eight columns must not make the page
           itself scroll sideways. -->
      <div class="storage__scroller">
        <table class="storage__table">
          <thead>
            <tr>
              <th scope="col">{{ t('Library') }}</th>
              <th scope="col" class="storage__number">{{ t('Version') }}</th>
              <th scope="col" class="storage__number">{{ t('Items') }}</th>
              <th scope="col" class="storage__number">{{ t('In the trash') }}</th>
              <th scope="col" class="storage__number">{{ t('Attachments') }}</th>
              <th scope="col" class="storage__number">{{ t('Size') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="library in report.libraries" :key="library.id">
              <td>
                <span class="storage__name">{{ library.name || address(library) }}</span>
                <span class="storage__address">{{ address(library) }}</span>
              </td>
              <td class="storage__number">{{ library.version }}</td>
              <td class="storage__number">{{ library.items }}</td>
              <td class="storage__number">{{ library.trashed }}</td>
              <td class="storage__number">{{ library.attachments }}</td>
              <td class="storage__number">{{ formatBytes(library.bytes) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.storage {
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

.storage__note {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}

.storage__warning {
  margin: 0;
  color: var(--md-sys-color-error);
  font-size: var(--md-sys-typescale-body-small-size);
}

.storage__scroller {
  overflow-x: auto;
}

.storage__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--md-sys-typescale-body-medium-size);
}

.storage__table th,
.storage__table td {
  padding: 0.35rem 0.5rem;
  text-align: left;
  white-space: nowrap;
}

.storage__table th {
  color: var(--md-sys-color-on-surface-variant);
  font-weight: 500;
}

.storage__table tbody tr + tr td {
  border-top: 1px solid var(--md-sys-color-outline-variant);
}

.storage__number {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.storage__name {
  display: block;
}

.storage__address {
  display: block;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}
</style>
