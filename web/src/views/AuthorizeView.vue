<script setup lang='ts'>
/**
 * Where an application asks for a library, and a person says yes or no.
 *
 * Reached by a redirect from `/oauth/authorize`, carrying nothing but an opaque
 * handle. Everything on this screen is read back from the server against that
 * handle, and none of it comes from the query string — which is the whole
 * reason the handle is opaque. A consent screen whose text is supplied by the
 * link that opened it describes whatever the link says it describes, and that
 * is the entire trick behind a convincing authorization phish.
 *
 * The route is guarded like any other, so somebody who is not signed in goes
 * through the ordinary sign-in first — with the second factor, the passkey or
 * the single sign-on their account actually has — and comes back here. There is
 * no password field on this page and there must never be one: a second way to
 * prove who you are is a second place for the second factor to be forgotten.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { ApiError, request } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()

interface OfferedCollection {
  key: string
  name: string
  parentKey: string | null
}

interface OfferedLibrary {
  id: string
  name: string
  type: string
  collections: OfferedCollection[]
}

interface GrantedResource {
  library: string
  libraryName: string
  collectionKey: string | null
  collectionName: string | null
}

interface PendingAuthorization {
  handle: string
  clientId: string
  name: string
  description: string
  scopes: string[]
  newScopes: string[]
  alreadyGranted: boolean
  reachesLibraries: boolean
  libraries: OfferedLibrary[]
  restricted: boolean
  grantedResources: GrantedResource[]
}

const auth = useAuthStore()
const route = useRoute()

const handle = computed(() =>
  typeof route.query.request === 'string' ? route.query.request : '',
)

const pending = ref<PendingAuthorization | null>(null)
const state = ref<'loading' | 'asking' | 'leaving' | 'failed'>('loading')
const failure = ref<string | null>(null)
const busy = ref(false)

/**
 * What each scope lets the application do, in a sentence rather than a token.
 *
 * A person is being asked to make a decision, and `library.read` is not a
 * decision anybody can make. Unknown scopes fall back to their own name rather
 * than being hidden: a scope this build does not recognise is still being
 * granted, and showing nothing would be the consent screen lying by omission.
 */
const DESCRIPTIONS: Record<string, () => string> = {
  openid: () => t('Know who you are'),
  profile: () => t('See your name and username'),
  email: () => t('See your email address'),
  groups: () => t('See which groups you belong to'),
  'library.read': () => t('Read everything in your library'),
  'library.write': () => t('Add, change and remove things in your library'),
  'notes.read': () => t('Read your notes'),
  'files.read': () => t('Download your attachments'),
  'groups.read': () => t('Read the group libraries you belong to'),
  'groups.write': () => t('Change the group libraries you belong to'),
}

function describe(scope: string): string {
  return DESCRIPTIONS[scope]?.() ?? scope
}

/** True when nothing on offer reaches a library — worth saying plainly. */
const identityOnly = computed(
  () =>
    pending.value !== null &&
    pending.value.scopes.every((scope) =>
      ['openid', 'profile', 'email', 'groups'].includes(scope),
    ),
)

function message(thrown: unknown): string {
  return thrown instanceof Error ? thrown.message : String(thrown)
}

/**
 * Whether the person is narrowing this grant, and to what.
 *
 * `false` is the default and means everything the scopes name, which is what
 * approving meant before this existed. Turning it on ticks nothing: an empty
 * choice is refused rather than silently granting everything, so the screen
 * cannot hand over a library because somebody stopped reading half way.
 */
const narrowing = ref(false)

/**
 * The resources ticked, each written the way the API addresses one:
 * `users/<id>`, `groups/<id>` or `<library>/collections/<key>`.
 */
const chosen = ref<Set<string>>(new Set())

function toggle(resource: string): void {
  const next = new Set(chosen.value)
  if (next.has(resource)) {
    next.delete(resource)
  } else {
    next.add(resource)
    // Ticking a whole library drops the collections picked inside it. The
    // server would read the wider row as the answer anyway, but sending both
    // would mean the screen said one thing and the request another.
    if (!resource.includes('/collections/')) {
      for (const entry of [...next]) {
        if (entry.startsWith(`${resource}/collections/`)) {
          next.delete(entry)
        }
      }
    }
  }
  chosen.value = next
}

/**
 * A library's collections in tree order, each with how deep it sits.
 *
 * Drawn as a tree because a granted collection means the branch under it, and
 * a flat list of names would not say so. Depth is computed rather than stored
 * so an orphaned collection — one whose parent this person cannot see — still
 * appears, at the top, instead of vanishing.
 */
function tree(library: OfferedLibrary): { entry: OfferedCollection; depth: number }[] {
  const byParent = new Map<string | null, OfferedCollection[]>()
  const known = new Set(library.collections.map((entry) => entry.key))
  for (const entry of library.collections) {
    const parent = entry.parentKey !== null && known.has(entry.parentKey) ? entry.parentKey : null
    byParent.set(parent, [...(byParent.get(parent) ?? []), entry])
  }

  const out: { entry: OfferedCollection; depth: number }[] = []
  const walk = (parent: string | null, depth: number): void => {
    for (const entry of byParent.get(parent) ?? []) {
      out.push({ entry, depth })
      walk(entry.key, depth + 1)
    }
  }
  walk(null, 0)
  return out
}

/** True when the person is narrowing but has ticked nothing. */
const nothingChosen = computed(() => narrowing.value && chosen.value.size === 0)

function describeGranted(resource: GrantedResource): string {
  return resource.collectionName === null
    ? resource.libraryName
    : `${resource.libraryName} → ${resource.collectionName}`
}

onMounted(async () => {
  if (!handle.value) {
    failure.value = t('That link is missing its request.')
    state.value = 'failed'
    return
  }
  try {
    pending.value = await request<PendingAuthorization>(
      `/web/oauth/pending/${encodeURIComponent(handle.value)}`,
    )
    state.value = 'asking'
  } catch (thrown) {
    failure.value =
      thrown instanceof ApiError && thrown.status === 404
        ? t('That request has expired or was never started. Start again in the application.')
        : message(thrown)
    state.value = 'failed'
  }
})

/**
 * Answer, then leave for the application's own address.
 *
 * `location.assign` rather than the router: the destination belongs to somebody
 * else and is not a route in this application. The state is set first so the
 * button cannot be pressed twice while the browser is on its way out.
 */
async function decide(approve: boolean): Promise<void> {
  busy.value = true
  failure.value = null
  try {
    const answer = await request<{ redirect: string }>(
      `/web/oauth/pending/${encodeURIComponent(handle.value)}`,
      {
        method: 'POST',
        body: {
          approve,
          // Absent rather than empty when nothing is being narrowed, because an
          // empty list and no list mean the same thing to the server and the
          // absent one is the one that reads as "I did not narrow this".
          ...(approve && narrowing.value ? { resources: [...chosen.value] } : {}),
        },
      },
    )
    state.value = 'leaving'
    window.location.assign(answer.redirect)
  } catch (thrown) {
    failure.value = message(thrown)
    busy.value = false
  }
}
</script>

<template>
  <section class="auth-form">
    <h1>{{ t('Connect an application') }}</h1>

    <p v-if="state === 'loading'" class="auth-form__lead">
      {{ t('Checking the request…') }}
    </p>

    <p v-else-if="state === 'leaving'" class="auth-form__lead">
      {{ t('Taking you back to the application…') }}
    </p>

    <template v-else-if="state === 'failed'">
      <p class="auth-form__error" role="alert">{{ failure }}</p>
      <AppButton
        variant="text"
        full-width
        @click="$router.push({ name: 'library' })"
      >
        {{ t('Go to your library') }}
      </AppButton>
    </template>

    <template v-else-if="pending">
      <p class="authorize__lead">
        <strong>{{ pending.name }}</strong>
        {{ t('wants to connect to your account') }}
        <strong>{{ auth.user?.username }}</strong
        >.
      </p>
      <p v-if="pending.description" class="authorize__description">
        {{ pending.description }}
      </p>

      <p v-if="pending.alreadyGranted" class="authorize__note">
        {{ t('You have already given this application these permissions.') }}
      </p>

      <p class="authorize__heading">{{ t('It will be able to:') }}</p>
      <ul class="authorize__grants">
        <li
          v-for="scope in pending.scopes"
          :key="scope"
          :class="{
            'authorize__grant--new': pending.newScopes.includes(scope),
          }"
        >
          {{ describe(scope) }}
          <span
            v-if="
              pending.newScopes.includes(scope) &&
              pending.scopes.length > pending.newScopes.length
            "
            class="authorize__badge"
          >
            {{ t('new') }}
          </span>
        </li>
      </ul>

      <p v-if="identityOnly" class="authorize__note">
        {{ t('It cannot read your library, your notes or your attachments.') }}
      </p>

      <!-- Where the grant reaches. Offered only when the scopes reach a library
           at all: narrowing an application that asked to know who you are would
           be a promise about nothing. The default is everything the scopes name,
           which is what approving has always meant. -->
      <template v-if="pending.reachesLibraries">
        <p v-if="pending.restricted" class="authorize__note">
          {{ t('Last time you limited it to:') }}
          <span v-for="(resource, index) in pending.grantedResources" :key="index">
            <template v-if="index > 0">, </template>{{ describeGranted(resource) }}
          </span>
        </p>

        <p class="authorize__heading">{{ t('Where it can reach:') }}</p>
        <div class="authorize__where">
          <label class="authorize__choice">
            <input v-model="narrowing" type="radio" :value="false" name="narrowing" />
            <span>{{ t('Everything the permissions above cover') }}</span>
          </label>
          <label class="authorize__choice">
            <input v-model="narrowing" type="radio" :value="true" name="narrowing" />
            <span>{{ t('Only the libraries and collections I choose') }}</span>
          </label>
        </div>

        <div v-if="narrowing" class="authorize__scope">
          <fieldset
            v-for="library in pending.libraries"
            :key="library.id"
            class="authorize__library"
          >
            <legend>{{ library.name }}</legend>
            <label class="authorize__choice">
              <input
                type="checkbox"
                :checked="chosen.has(library.id)"
                @change="toggle(library.id)"
              />
              <span>{{ t('All of it') }}</span>
            </label>
            <label
              v-for="row in tree(library)"
              :key="row.entry.key"
              class="authorize__choice"
              :style="{ paddingLeft: `${row.depth * 16}px` }"
            >
              <input
                type="checkbox"
                :disabled="chosen.has(library.id)"
                :checked="chosen.has(`${library.id}/collections/${row.entry.key}`)"
                @change="toggle(`${library.id}/collections/${row.entry.key}`)"
              />
              <span>{{ row.entry.name }}</span>
            </label>
            <p v-if="library.collections.length === 0" class="authorize__note">
              {{ t('No collections yet.') }}
            </p>
          </fieldset>

          <p class="authorize__note">
            {{
              t(
                'Choosing a collection also includes everything nested inside it. The application will not be able to change your collections, saved searches, settings or tags.',
              )
            }}
          </p>
          <p v-if="nothingChosen" class="authorize__note" role="alert">
            {{ t('Choose at least one library or collection, or allow everything above.') }}
          </p>
        </div>
      </template>

      <p class="authorize__note">
        {{
          t('You can disconnect it at any time in Settings, under Connected applications.')
        }}
      </p>

      <p v-if="failure" class="auth-form__error" role="alert">{{ failure }}</p>

      <AppButton
        type="button"
        full-width
        :loading="busy"
        :disabled="nothingChosen"
        @click="decide(true)"
      >
        {{ t('Allow') }}
      </AppButton>
      <AppButton
        variant="text"
        full-width
        :disabled="busy"
        @click="decide(false)"
      >
        {{ t('Cancel') }}
      </AppButton>
    </template>
  </section>
</template>

<style scoped>
@import '@/styles/auth-form.css';

.authorize__lead {
  margin: 0;
  color: var(--md-sys-color-on-surface);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.authorize__description {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}

.authorize__heading {
  margin: 0;
  color: var(--md-sys-color-on-surface);
  font-size: var(--md-sys-typescale-label-large-size);
}

.authorize__grants {
  margin: 0;
  padding-left: var(--md-spacing-5);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
}

/* What is being added this time, where consent has been given before. Marked
   rather than listed on its own, so the whole grant is still readable at once. */
.authorize__grant--new {
  color: var(--md-sys-color-on-surface);
}

.authorize__badge {
  margin-left: var(--md-spacing-2);
  padding: 0 var(--md-spacing-2);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  font-size: var(--md-sys-typescale-label-small-size);
}

.authorize__note {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}

.authorize__where,
.authorize__scope {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

.authorize__choice {
  display: flex;
  align-items: center;
  gap: var(--md-spacing-2);
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.authorize__library {
  margin: 0;
  padding: var(--md-spacing-3);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-small);
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
}

.authorize__library legend {
  padding: 0 var(--md-spacing-1);
  color: var(--md-sys-color-on-surface);
  font-size: var(--md-sys-typescale-label-large-size);
}
</style>
