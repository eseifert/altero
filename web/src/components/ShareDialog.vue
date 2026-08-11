<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { formatDate } from '@/formats'
import { useModal } from '@/modal'
import type { CollectionShare } from '@/stores/shares'

/**
 * The links that show one collection to whoever holds them.
 *
 * A link is not sync. Nothing here reaches the sync protocol, no library
 * version moves, and no Zotero client learns that any of this exists — the
 * request people have been making since 2008 is answered as a page, because as
 * sync it would mean lying to clients about what a library holds.
 *
 * So the three questions the form asks are the three a page can answer. How
 * much of the tree goes: the branch, which is what the sidebar shows when you
 * click a collection, or the one collection alone. Whether the files go, which
 * is a separate decision from the metadata for the same reason the publishing
 * wizard makes it separately — a reading list is not the same thing to hand out
 * as the PDFs. And how long, because a link given to a seminar in March is not
 * one to leave working in November.
 *
 * The link itself is shown once, by the request that made it. The server keeps
 * nothing it could be rebuilt from, so this dialog is the only place it ever
 * appears; afterwards the list can say a link exists and not what it is.
 */
const props = defineProps<{
  collectionName: string
  shares: CollectionShare[]
  /** The link just made, if this is the moment after making one. */
  issued: CollectionShare | null
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  create: [terms: { subcollections: boolean; files: boolean; expires: string | null }]
  revoke: [shareId: number]
  cancel: []
}>()

const { t } = useI18n()

const subcollections = ref(true)
const files = ref(true)
/** A local date, from `<input type="date">`. Empty means it never expires. */
const expires = ref('')
const copied = ref(false)

const dialog = useTemplateRef<HTMLDialogElement>('dialog')

useModal(dialog, () => emit('cancel'))

onMounted(() => dialog.value?.focus())

/* A fresh link deserves a fresh "copy" button: the acknowledgement belongs to
   the link it was pressed for and not to whatever is on screen now. */
watch(
  () => props.issued?.id,
  () => {
    copied.value = false
  },
)

const forThisCollection = computed(() =>
  props.shares.filter((share) => share.collectionName === props.collectionName),
)

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('cancel')
}

function submit(): void {
  emit('create', {
    subcollections: subcollections.value,
    files: files.value,
    /* End of the chosen day rather than its first instant: somebody who says a
       link is good until Friday means through Friday. */
    expires: expires.value ? `${expires.value}T23:59:59Z` : null,
  })
}

async function copy(url: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(url)
    copied.value = true
  } catch {
    /* No clipboard, or permission refused. The link is on screen and can be
       selected by hand, so this is not worth an error message. */
    copied.value = false
  }
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog"
    :aria-label="t('Share this collection')"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <div class="dialog__body">
      <h2 class="dialog__title">{{ t('Share this collection') }}</h2>
      <p class="share__intro">
        {{
          t(
            'Anybody with the link can read “{name}”. They will not need an account here, and they cannot change anything.',
            { name: collectionName },
          )
        }}
      </p>

      <!-- Shown once, and never again from anywhere. -->
      <div v-if="issued?.url" class="share__issued">
        <label class="dialog__label" for="share-url">{{ t('The link') }}</label>
        <div class="share__url-row">
          <input id="share-url" class="dialog__field" type="text" readonly :value="issued.url" />
          <AppButton variant="text" @click="copy(issued.url)">
            {{ copied ? t('Copied') : t('Copy') }}
          </AppButton>
        </div>
        <p class="share__once">
          {{ t('Copy it now. It is not stored anywhere it can be read back.') }}
        </p>
      </div>

      <form v-else class="share__form" @submit.prevent="submit">
        <label class="share__choice">
          <input v-model="subcollections" type="checkbox" />
          <span>{{ t('Include the collections inside this one') }}</span>
        </label>
        <label class="share__choice">
          <input v-model="files" type="checkbox" />
          <span>{{ t('Include attached files') }}</span>
        </label>

        <label class="dialog__label" for="share-expires">{{ t('Stops working on') }}</label>
        <input id="share-expires" v-model="expires" class="dialog__field" type="date" />
        <p class="share__hint">{{ t('Leave this empty for a link that never stops working.') }}</p>

        <p v-if="error" class="dialog__error" role="alert">{{ error }}</p>

        <div class="dialog__actions">
          <AppButton variant="text" :disabled="busy" @click="emit('cancel')">
            {{ t('Cancel') }}
          </AppButton>
          <AppButton type="submit" :loading="busy">{{ t('Create a link') }}</AppButton>
        </div>
      </form>

      <section v-if="forThisCollection.length" class="share__existing">
        <h3 class="share__subtitle">{{ t('Links to this collection') }}</h3>
        <ul class="share__list">
          <li v-for="share in forThisCollection" :key="share.id" class="share__item">
            <div class="share__item-text">
              <p class="share__item-name">
                {{
                  share.subcollections
                    ? t('The collection and everything inside it')
                    : t('This collection only')
                }}
                <template v-if="!share.files"> — {{ t('without files') }}</template>
              </p>
              <p class="share__item-detail">
                {{ t('Made {date}', { date: formatDate(share.created) }) }}
                <template v-if="share.expires">
                  · {{ t('Stops working {date}', { date: formatDate(share.expires) }) }}
                </template>
                <template v-if="share.lastUsed">
                  · {{ t('Last opened {date}', { date: formatDate(share.lastUsed) }) }}
                </template>
                <template v-else> · {{ t('Never opened') }}</template>
              </p>
            </div>
            <AppButton variant="text" :disabled="busy" @click="emit('revoke', share.id)">
              {{ t('Revoke') }}
            </AppButton>
          </li>
        </ul>
      </section>

      <div v-if="issued?.url" class="dialog__actions">
        <AppButton @click="emit('cancel')">{{ t('Done') }}</AppButton>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.share__intro,
.share__hint,
.share__once,
.share__item-detail {
  color: var(--md-sys-color-on-surface-variant);
  font-size: 0.85rem;
}

.share__form,
.share__issued,
.share__existing {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.share__choice {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* The field takes what is left: a share link is longer than the dialog is wide
   and the button must not be pushed off the end of it. */
.share__url-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.share__url-row .dialog__field {
  flex: 1 1 auto;
  min-width: 0;
}

.share__subtitle {
  font-size: 0.95rem;
  font-weight: 600;
  margin: 0;
}

.share__list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  list-style: none;
  margin: 0;
  padding: 0;
}

.share__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.share__item-text {
  min-width: 0;
}

.share__item-name,
.share__item-detail {
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
