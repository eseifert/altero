<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import ItemTypeIcon from '@/components/ItemTypeIcon.vue'

interface LibrarySummary {
  id: number
  type: string
  name: string
  version: number
}

interface ItemEnvelope {
  key: string
  version: number
  data: Record<string, unknown> & { itemType: string; title?: string }
  meta: { creatorSummary?: string; parsedDate?: string; numChildren?: number }
}

const libraries = ref<LibrarySummary[]>([])
const items = ref<ItemEnvelope[]>([])
const total = ref(0)
const loading = ref(true)
const failure = ref<string | null>(null)

onMounted(async () => {
  try {
    libraries.value = await request<LibrarySummary[]>('/web/libraries')
    const first = libraries.value[0]
    if (first) {
      const page = await request<{ items: ItemEnvelope[]; total: number }>(
        `/web/libraries/${first.id}/items?limit=50`,
      )
      items.value = page.items
      total.value = page.total
    }
  } catch (thrown) {
    failure.value = thrown instanceof Error ? thrown.message : String(thrown)
  } finally {
    loading.value = false
  }
})

function titleOf(item: ItemEnvelope): string {
  return (item.data.title as string) || '(untitled)'
}
</script>

<template>
  <section class="library">
    <header class="library__header">
      <h1>{{ libraries[0]?.name ?? 'Library' }}</h1>
      <p v-if="!loading" class="library__count">
        {{ total }} {{ total === 1 ? 'item' : 'items' }}
      </p>
    </header>

    <p v-if="loading" class="library__state">Loading…</p>
    <p v-else-if="failure" class="library__state library__state--error" role="alert">
      {{ failure }}
    </p>
    <p v-else-if="items.length === 0" class="library__state">
      Nothing here yet. Point the Zotero desktop app at this server and sync.
    </p>

    <ul v-else class="library__items">
      <li v-for="item in items" :key="item.key" class="library__item">
        <ItemTypeIcon :item-type="item.data.itemType" />
        <span class="library__title">{{ titleOf(item) }}</span>
        <span class="library__creator">{{ item.meta?.creatorSummary ?? '' }}</span>
        <span class="library__date">{{ item.meta?.parsedDate ?? '' }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.library {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-4);
}

.library__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--md-spacing-4);
}

.library__count,
.library__state {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.library__state--error {
  color: var(--md-sys-color-error);
}

.library__items {
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  overflow: hidden;
}

.library__item {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  align-items: center;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
}

.library__item:last-child {
  border-bottom: none;
}

.library__item:hover {
  background: var(--md-sys-color-surface-container-low);
}

.library__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library__creator,
.library__date {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
  white-space: nowrap;
}

@media (max-width: 640px) {
  .library__item {
    grid-template-columns: auto 1fr;
  }

  .library__creator,
  .library__date {
    display: none;
  }
}
</style>
