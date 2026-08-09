<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import { useModal } from '@/modal'
import { creativeCommonsLicense, licenseFor } from '@/publications/licenses'

/**
 * Putting one item into My Publications, on the terms the desktop client asks.
 *
 * Publishing is not a checkbox. `Zotero.Items.addToPublications` takes five
 * answers, and `publicationsDialog.js` collects them over three pages: what
 * goes along, whether the work may be shared, and under which licence. The
 * same three are here, in the same order, with the same rules about which of
 * them can be skipped — because the questions are not the interface's, they
 * are what publishing somebody's work means.
 *
 * The shape of the walk, which is `onWizardNext` in the client:
 *
 * - No files to publish, no licence to choose: the first page is the last one,
 *   and nothing is written to the Rights field.
 * - Files, and "keep the existing Rights field": the second page is the last,
 *   because the reader has said what the terms are and it is not this dialog's
 *   business to overwrite them.
 * - Files, reserved rights or the public domain: also the second page. Only
 *   Creative Commons has anything left to ask.
 *
 * Confirming authorship is what unlocks the walk at all, and its wording
 * changes with the files checkbox: distributing somebody's PDF is a different
 * claim from listing their paper.
 */
const props = defineProps<{
  /** What the item is called, so the dialog says what it is about. */
  title: string
  /** Whether the item has stored attachments — the checkbox is about those. */
  hasFiles: boolean
  /** Whether it has child notes. */
  hasNotes: boolean
  /** Whether its Rights field already says something. */
  hasRights: boolean
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  submit: [
    terms: {
      includeFiles: boolean
      includeNotes: boolean
      license: string | null
      keepRights: boolean
    },
  ]
  cancel: []
}>()

const { t } = useI18n()

type Page = 'intro' | 'sharing' | 'license'

const page = ref<Page>('intro')

const includeFiles = ref(false)
const includeNotes = ref(false)
/** "I created this work." Nothing advances until this is answered. */
const confirmed = ref(false)
const keepRights = ref(false)
const sharing = ref<'reserved' | 'cc' | 'cc0'>('reserved')
/* The client's own defaults: the most restrictive of each pair, so a reader
   who presses through the last page without reading it has given away the
   least rather than the most. */
const adaptations = ref<'yes' | 'no' | 'sharealike'>('no')
const commercial = ref<'yes' | 'no'>('no')

/**
 * Whether the Rights field stands, which ends the questions.
 *
 * `updateSharingPage` in the client hides the sharing options entirely in this
 * case: there is no point choosing a licence that will not be written.
 */
const rightsStand = computed(() => props.hasRights && keepRights.value)

/** The licence the answers so far amount to, or null while there is none. */
const license = computed<string | null>(() => {
  if (!includeFiles.value || rightsStand.value) return null
  if (sharing.value !== 'cc') return sharing.value
  /* Creative Commons is not an answer on its own — it is the question the last
     page asks — so there is no licence to name until that page is reached. */
  if (page.value !== 'license') return null
  return creativeCommonsLicense(adaptations.value, commercial.value)
})

const chosen = computed(() => (license.value ? licenseFor(license.value) : undefined))

/** Whether this page is the last one, which decides what the button says. */
const finishes = computed(() => {
  if (page.value === 'license') return true
  if (page.value === 'sharing') return rightsStand.value || sharing.value !== 'cc'
  return !includeFiles.value
})

const nextLabel = computed(() => {
  if (finishes.value) return t('Add to My Publications')
  return page.value === 'intro' ? t('Next: Sharing') : t('Next: Choose a License')
})

const heading = computed(() => {
  if (page.value === 'sharing') return t('Choose how your work may be shared')
  if (page.value === 'license') return t('Choose a Creative Commons license')
  return t('Add to My Publications')
})

const dialog = useTemplateRef<HTMLDialogElement>('dialog')

useModal(dialog, () => emit('cancel'))

/* Each page opens on its own first control, which is `updateFocus` in the
   client. Without it the focus stays on the button that turned the page, and
   a keyboard reader is at the bottom of a page they have not read yet. Found
   in the DOM rather than held as a ref, because which control comes first
   depends on the answers — the Rights checkbox is there only sometimes. */
function focusFirst(): void {
  void nextTick(() => {
    dialog.value?.querySelector<HTMLInputElement>('input:not([disabled])')?.focus()
  })
}

onMounted(focusFirst)
watch(page, focusFirst)

function backdrop(event: MouseEvent): void {
  if (event.target === dialog.value) emit('cancel')
}

function back(): void {
  page.value = page.value === 'license' ? 'sharing' : 'intro'
}

function advance(): void {
  if (!finishes.value) {
    page.value = page.value === 'intro' ? 'sharing' : 'license'
    return
  }
  emit('submit', {
    includeFiles: includeFiles.value,
    includeNotes: includeNotes.value,
    license: license.value,
    /* Meaningless where the item has no Rights field value, and sent anyway:
       the server applies the same rule the client does — a licence is written
       when it was not asked to keep what is there, or there is nothing to
       keep. */
    keepRights: keepRights.value,
  })
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog dialog--wide"
    :aria-label="t('Add “{name}” to My Publications', { name: title })"
    @cancel.prevent="emit('cancel')"
    @click="backdrop"
  >
    <form class="dialog__body" @submit.prevent="advance">
      <h2 class="dialog__title">{{ heading }}</h2>
      <p v-if="page === 'intro'" class="dialog__what">{{ title }}</p>

      <template v-if="page === 'intro'">
        <!--
          Zotero's own warning, minus the part about zotero.org: what is
          published here is published from this server, and the reader is
          entitled to know that before they agree to it rather than after.
        -->
        <p class="dialog__note">
          {{
            t(
              'Anyone can read what you put in My Publications, without an account here and without a key. Files you include are published under the licence you choose. Only add work you created yourself, and only include files you have the right to distribute.',
            )
          }}
        </p>

        <label class="dialog__check">
          <input v-model="includeFiles" type="checkbox" :disabled="!hasFiles || busy" />
          <span>{{ t('Include files') }}</span>
        </label>
        <label class="dialog__check">
          <input v-model="includeNotes" type="checkbox" :disabled="!hasNotes || busy" />
          <span>{{ t('Include notes') }}</span>
        </label>

        <p class="dialog__note">
          {{ t('You can change what is shown at any time from My Publications.') }}
        </p>

        <!-- The claim being made, and the only control that has to be
             answered. Its wording follows the files checkbox, because
             distributing somebody's PDF is a larger claim than listing their
             paper. -->
        <label class="dialog__check publish__claim">
          <input v-model="confirmed" type="checkbox" :disabled="busy" />
          <span v-if="includeFiles">
            {{ t('I created this work and have the rights to distribute the files included.') }}
          </span>
          <span v-else>{{ t('I created this work.') }}</span>
        </label>
      </template>

      <template v-else-if="page === 'sharing'">
        <label v-if="hasRights" class="dialog__check">
          <input v-model="keepRights" type="checkbox" :disabled="busy" />
          <span>{{ t('Keep the existing Rights field') }}</span>
        </label>

        <template v-if="!rightsStand">
          <p class="dialog__note">
            {{
              t(
                'You can reserve all rights to your work, license it under a Creative Commons license, or dedicate it to the public domain. Either way the work itself is published here for anyone to read.',
              )
            }}
          </p>

          <fieldset class="publish__group">
            <legend class="dialog__label">
              {{ t('Would you like to allow your work to be shared by others?') }}
            </legend>
            <label class="dialog__check">
              <input v-model="sharing" type="radio" value="reserved" :disabled="busy" />
              <span>{{ t('No, publish my work here only') }}</span>
            </label>
            <label class="dialog__check">
              <input v-model="sharing" type="radio" value="cc" :disabled="busy" />
              <span>{{ t('Yes, under a Creative Commons license') }}</span>
            </label>
            <label class="dialog__check">
              <input v-model="sharing" type="radio" value="cc0" :disabled="busy" />
              <span>{{ t('Yes, and place my work in the public domain') }}</span>
            </label>
          </fieldset>
        </template>
      </template>

      <template v-else>
        <p class="dialog__note">
          {{
            t(
              'A Creative Commons license allows others to copy and redistribute your work as long as they give appropriate credit, provide a link to the license, and indicate if changes were made. Additional conditions can be specified below.',
            )
          }}
        </p>

        <fieldset class="publish__group">
          <legend class="dialog__label">
            {{ t('Allow adaptations of your work to be shared?') }}
          </legend>
          <label class="dialog__check">
            <input v-model="adaptations" type="radio" value="no" :disabled="busy" />
            <span>{{ t('No') }}</span>
          </label>
          <label class="dialog__check">
            <input v-model="adaptations" type="radio" value="sharealike" :disabled="busy" />
            <span>{{ t('Yes, as long as others share alike') }}</span>
          </label>
          <label class="dialog__check">
            <input v-model="adaptations" type="radio" value="yes" :disabled="busy" />
            <span>{{ t('Yes') }}</span>
          </label>
        </fieldset>

        <fieldset class="publish__group">
          <legend class="dialog__label">{{ t('Allow commercial uses of your work?') }}</legend>
          <label class="dialog__check">
            <input v-model="commercial" type="radio" value="no" :disabled="busy" />
            <span>{{ t('No') }}</span>
          </label>
          <label class="dialog__check">
            <input v-model="commercial" type="radio" value="yes" :disabled="busy" />
            <span>{{ t('Yes') }}</span>
          </label>
        </fieldset>
      </template>

      <!--
        What the item's Rights field will say, in the words it will say it in.
        Untranslated on purpose — see `publications/licenses.ts` — so that the
        name here and the name stored are one string.
      -->
      <p v-if="chosen" class="publish__license">
        <a v-if="chosen.url" :href="chosen.url" target="_blank" rel="noreferrer">
          {{ chosen.name }}
        </a>
        <span v-else>{{ chosen.name }}</span>
      </p>
      <p v-if="chosen && chosen.id !== 'reserved'" class="dialog__note">
        {{
          chosen.id === 'cc0'
            ? t(
                'Dedicating your work to the public domain cannot be undone, even if you later choose different terms or stop publishing the work.',
              )
            : t(
                'A Creative Commons license cannot be revoked, even if you later choose different terms or stop publishing the work.',
              )
        }}
      </p>

      <p v-if="error" class="dialog__error" role="alert">{{ error }}</p>

      <div class="dialog__actions">
        <AppButton v-if="page !== 'intro'" variant="text" :disabled="busy" @click="back">
          {{ t('Back') }}
        </AppButton>
        <span class="dialog__spacer"></span>
        <AppButton variant="text" :disabled="busy" @click="emit('cancel')">
          {{ t('Cancel') }}
        </AppButton>
        <AppButton type="submit" :loading="busy" :disabled="!confirmed">
          {{ nextLabel }}
        </AppButton>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
/* A group of answers to one question. The browser's own fieldset border would
   box each question separately, which reads as three forms rather than one. */
.publish__group {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
  margin: 0;
  padding: 0;
  border: none;
}

/* The claim stands apart from the two checkboxes above it: it is not another
   thing to include, it is the sentence the reader is signing. */
.publish__claim {
  padding-top: var(--md-spacing-2);
  border-top: 1px solid var(--md-sys-color-outline-variant, currentColor);
}

.publish__license {
  margin: 0;
  font-size: var(--md-sys-typescale-body-medium-size);
}
</style>
