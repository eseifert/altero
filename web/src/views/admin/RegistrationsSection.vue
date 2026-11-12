<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import ConfirmIdentity from '@/components/ConfirmIdentity.vue'
import { formatDate } from '@/formats'
import { message, usePanel } from './panel'

interface Application {
  id: number
  username: string
  email: string
  displayName: string
  created: string
  expires: string
}
const { t } = useI18n()
const { busy, failure, attempt } = usePanel()
const rows = ref<Application[]>([])
const selected = ref<Application | null>(null)
const password = ref('')
const confirmed = ref(false)
const after = ref(0)
const loading = ref(false)
const proofRevision = ref(0)

async function reload(): Promise<void> {
  loading.value = true
  try {
    rows.value = (await request<{ requests: Application[] }>(`/web/admin/registrations?after_id=${after.value}&limit=50`)).requests
    selected.value = null
    password.value = ''
  } finally { loading.value = false }
}
async function page(cursor: number): Promise<void> {
  after.value = cursor
  try { await reload() } catch (thrown) { failure.value = message(thrown) }
}
function choose(row: Application): void {
  selected.value = row
  password.value = ''
  confirmed.value = false
}
async function decide(action: 'approve' | 'reject'): Promise<void> {
  const row = selected.value
  if (!row) return
  await attempt(async () => {
    try {
      await request(`/web/admin/registrations/${row.id}/${action}`, {
        method: 'POST', body: action === 'approve' ? { currentPassword: password.value } : {},
      })
      await reload()
    } catch (thrown) {
      password.value = ''
      confirmed.value = false
      proofRevision.value++
      throw thrown
    }
  }, action === 'approve' ? t('Registration approved.') : t('Registration rejected.'))
}
onMounted(() => page(0))
</script>

<template>
  <section class="card registrations">
    <p>{{ t('Only verified requests appear here. Approval creates an account; the applicant then chooses a password.') }}</p>
    <AppButton variant="text" :disabled="busy || loading" @click="page(after)">{{ t('Refresh') }}</AppButton>
    <p v-if="loading" role="status">{{ t('Loading…') }}</p>
    <p v-else-if="!rows.length">{{ t('No requests await approval.') }}</p>
    <ul v-else class="registrations__list">
      <li v-for="row in rows" :key="row.id" class="registrations__row">
        <div>
          <strong dir="auto">{{ row.username }}</strong>
          <span v-if="row.displayName" dir="auto"> · {{ row.displayName }}</span>
          <p dir="auto">{{ row.email }}</p>
          <p>{{ t('Created {date}', { date: formatDate(row.created) }) }}</p>
          <p>{{ t('Request deadline: {date}', { date: formatDate(row.expires) }) }}</p>
        </div>
        <AppButton variant="text" :disabled="busy" @click="choose(row)">{{ t('Review') }}</AppButton>
        <form v-if="selected?.id === row.id" class="registrations__decision" @submit.prevent="decide('approve')">
          <ConfirmIdentity :key="proofRevision" v-model="password" v-model:ready="confirmed" />
          <div class="registrations__actions">
            <AppButton type="submit" :disabled="!confirmed || busy" :loading="busy">{{ t('Approve') }}</AppButton>
            <AppButton type="button" variant="text" :disabled="busy" @click="decide('reject')">{{ t('Reject') }}</AppButton>
          </div>
        </form>
      </li>
    </ul>
    <div class="registrations__actions">
      <AppButton v-if="after" variant="text" :disabled="busy || loading" @click="page(0)">{{ t('First page') }}</AppButton>
      <AppButton v-if="rows.length === 50" variant="text" :disabled="busy || loading" @click="page(rows[rows.length - 1]!.id)">{{ t('Next page') }}</AppButton>
    </div>
  </section>
</template>

<style scoped>
.registrations { display: grid; gap: var(--md-spacing-3); }
.registrations__list { list-style: none; margin: 0; padding: 0; }
.registrations__row { padding-block: var(--md-spacing-3); border-block-end: 1px solid var(--md-sys-color-outline-variant); overflow-wrap: anywhere; }
.registrations__row p { margin-block: var(--md-spacing-1); }
.registrations__decision { display: grid; gap: var(--md-spacing-3); }
.registrations__actions { display: flex; flex-wrap: wrap; gap: var(--md-spacing-2); }
</style>
