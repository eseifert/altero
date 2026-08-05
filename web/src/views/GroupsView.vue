<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import AppButton from '@/components/AppButton.vue'
import AppTextField from '@/components/AppTextField.vue'
import { useAuthStore } from '@/stores/auth'
import {
  useGroupStore,
  type ActivityEntry,
  type Group,
  type NotificationKind,
  type Role,
} from '@/stores/groups'
import { formatDate } from '@/formats'

const { t } = useI18n()

const auth = useAuthStore()
const store = useGroupStore()

/** The group whose panel is open, refetched so it carries members. */
const open = ref<Group | null>(null)
const creating = ref(false)

const newName = ref('')
const newDescription = ref('')

const inviteEmail = ref('')
const inviteRole = ref<Role>('member')

/** Held until confirmed: deleting a group takes a library with it. */
const confirming = ref<'delete' | 'leave' | null>(null)

onMounted(() => store.load())

const canAdminister = computed(() => open.value?.role === 'admin')

/**
 * The four kinds, in the order the digest itself lists them, so the panel and
 * the message a person receives read the same way round.
 *
 * The labels are functions rather than strings so they are translated when the
 * list is rendered, not once when this module is first evaluated -- which
 * would freeze them in whatever language happened to be active then.
 */
const NOTIFICATION_KINDS: { name: NotificationKind; label: () => string }[] = [
  { name: 'itemsChanged', label: () => t('Items added or changed') },
  { name: 'itemsDeleted', label: () => t('Items deleted') },
  { name: 'membersChanged', label: () => t('People joining or leaving') },
  { name: 'collectionsChanged', label: () => t('Collections added or changed') },
]

async function setNotification(kind: NotificationKind, wanted: boolean): Promise<void> {
  if (!open.value) {
    return
  }
  const id = open.value.id
  await store.setNotification(id, kind, wanted, t('Saved.'))
  // The store holds the server's answer for the whole set; mirror it onto the
  // open panel, which is a copy fetched separately and would otherwise show
  // the old value until the group is reopened.
  const held = store.groups.find((group) => group.id === id)?.notifications
  if (held && open.value) {
    open.value.notifications = held
  }
}

/** What has happened in the open group, newest first. */
const log = ref<ActivityEntry[]>([])

/**
 * One line per entry, pluralised on the count.
 *
 * The wording matches the digest a member receives by mail, so the same change
 * reads the same way whichever way somebody hears about it.
 */
function describe(entry: ActivityEntry): string {
  const count = entry.count
  switch (entry.kind) {
    case 'items_deleted':
      return t('{count} item deleted | {count} items deleted', { count }, count)
    case 'members_changed':
      return t('{count} membership changed | {count} memberships changed', { count }, count)
    case 'collections_changed':
      return t(
        '{count} collection added or changed | {count} collections added or changed',
        { count },
        count,
      )
    default:
      return t('{count} item added or changed | {count} items added or changed', { count }, count)
  }
}

async function show(group: Group): Promise<void> {
  open.value = (await store.read(group.id)) ?? null
  confirming.value = null
  log.value = open.value ? ((await store.readActivity(open.value.id))?.activity ?? []) : []
}

function close(): void {
  open.value = null
  confirming.value = null
}

async function refresh(): Promise<void> {
  if (open.value) {
    open.value = (await store.read(open.value.id)) ?? null
  }
  await store.load()
}

async function create(): Promise<void> {
  if (!newName.value.trim()) {
    return
  }
  const group = await store.create(
    { name: newName.value.trim(), description: newDescription.value.trim() },
    t('Group created.'),
  )
  if (group) {
    newName.value = ''
    newDescription.value = ''
    creating.value = false
    await show(group)
  }
}

async function setPolicy(field: keyof Group, value: string): Promise<void> {
  if (!open.value) return
  await store.update(open.value.id, { [field]: value }, t('Group saved.'))
  await refresh()
}

async function rename(name: string, description: string): Promise<void> {
  if (!open.value) return
  await store.update(open.value.id, { name, description }, t('Group saved.'))
  await refresh()
}

async function setRole(memberId: number, role: Role): Promise<void> {
  if (!open.value) return
  await store.setRole(open.value.id, memberId, role)
  await refresh()
}

async function removeMember(memberId: number): Promise<void> {
  if (!open.value) return
  await store.removeMember(open.value.id, memberId)
  if (memberId === auth.user?.id) {
    close()
  } else {
    await refresh()
  }
}

async function transfer(memberId: number): Promise<void> {
  if (!open.value) return
  await store.transfer(open.value.id, memberId, t('The group has a new owner.'))
  await refresh()
}

async function invite(): Promise<void> {
  if (!open.value || !inviteEmail.value.trim()) return
  await store.invite(open.value.id, inviteEmail.value.trim(), inviteRole.value, t('Invitation sent.'))
  inviteEmail.value = ''
  await refresh()
}

async function revoke(invitationId: number): Promise<void> {
  await store.revokeInvitation(invitationId)
  await refresh()
}

async function destroy(): Promise<void> {
  if (!open.value) return
  const id = open.value.id
  close()
  await store.remove(id, t('Group deleted.'))
}

/* The metadata form is bound to its own refs so a half-typed name is not sent
   on every keystroke, and so leaving the panel discards it. */
const editedName = computed({
  get: () => open.value?.name ?? '',
  set: (value: string) => {
    if (open.value) open.value.name = value
  },
})
const editedDescription = computed({
  get: () => open.value?.description ?? '',
  set: (value: string) => {
    if (open.value) open.value.description = value
  },
})
</script>

<template>
  <section class="groups">
    <header class="groups__header">
      <h1>{{ t('Groups') }}</h1>
      <AppButton v-if="!creating && !open" @click="creating = true">
        {{ t('New group') }}
      </AppButton>
      <AppButton v-if="open" variant="text" @click="close">{{ t('Back to groups') }}</AppButton>
    </header>

    <p v-if="store.error" class="groups__error" role="alert">{{ store.error }}</p>
    <p v-else-if="store.notice" class="groups__notice" role="status">{{ store.notice }}</p>

    <!-- Creating -->
    <form v-if="creating && !open" class="panel" @submit.prevent="create">
      <h2>{{ t('New group') }}</h2>
      <p class="panel__lead">
        {{ t('A group is a library of its own, shared with the people you add to it.') }}
      </p>
      <AppTextField v-model="newName" :label="t('Name')" required autofocus />
      <AppTextField v-model="newDescription" :label="t('Description')" :hint="t('Optional')" />
      <div class="panel__actions">
        <AppButton variant="text" @click="creating = false">{{ t('Cancel') }}</AppButton>
        <AppButton type="submit" :loading="store.busy">{{ t('Create group') }}</AppButton>
      </div>
    </form>

    <!-- The list -->
    <template v-if="!open && !creating">
      <p v-if="!store.hasGroups && !store.busy" class="groups__empty">
        {{ t('You are not in any groups yet.') }}
      </p>
      <ul v-else class="groups__list">
        <li v-for="group in store.groups" :key="group.id">
          <button class="card" type="button" @click="show(group)">
            <span class="card__title">{{ group.name }}</span>
            <span class="card__detail">
              {{ t('{count} member | {count} members', { count: group.numMembers }, group.numMembers) }}
              ·
              {{ t('{count} item | {count} items', { count: group.numItems }, group.numItems) }}
              ·
              {{ group.role === 'admin' ? t('Administrator') : t('Member') }}
            </span>
            <span v-if="group.description" class="card__detail">{{ group.description }}</span>
          </button>
        </li>
      </ul>
    </template>

    <!-- One group -->
    <div v-if="open" class="panel">
      <h2>{{ open.name }}</h2>
      <p class="panel__lead">
        {{ t('Sync clients see this as group {id}.', { id: open.groupId }) }}
      </p>

      <template v-if="canAdminister">
        <AppTextField v-model="editedName" :label="t('Name')" />
        <AppTextField v-model="editedDescription" :label="t('Description')" />
        <div class="panel__actions">
          <AppButton :loading="store.busy" @click="rename(editedName, editedDescription)">
            {{ t('Save') }}
          </AppButton>
        </div>

        <h3>{{ t('Who may do what') }}</h3>
        <label class="choice">
          <span>{{ t('Visibility') }}</span>
          <select :value="open.type" @change="setPolicy('type', ($event.target as HTMLSelectElement).value)">
            <option value="Private">{{ t('Private') }}</option>
            <option value="PublicClosed">{{ t('Public, invitation only') }}</option>
            <option value="PublicOpen">{{ t('Public') }}</option>
          </select>
        </label>
        <label class="choice">
          <span>{{ t('Who may read the library') }}</span>
          <select
            :value="open.libraryReading"
            @change="setPolicy('libraryReading', ($event.target as HTMLSelectElement).value)"
          >
            <option value="members">{{ t('Members') }}</option>
            <option value="all">{{ t('Anyone') }}</option>
          </select>
        </label>
        <p v-if="open.libraryReading === 'all' && open.type === 'Private'" class="choice__note">
          {{ t('A private group stays private whatever this says. Make it public as well to share it.') }}
        </p>
        <label class="choice">
          <span>{{ t('Who may add and change items') }}</span>
          <select
            :value="open.libraryEditing"
            @change="setPolicy('libraryEditing', ($event.target as HTMLSelectElement).value)"
          >
            <option value="members">{{ t('Members') }}</option>
            <option value="admins">{{ t('Administrators') }}</option>
          </select>
        </label>
        <label class="choice">
          <span>{{ t('Who may upload files') }}</span>
          <select
            :value="open.fileEditing"
            @change="setPolicy('fileEditing', ($event.target as HTMLSelectElement).value)"
          >
            <option value="none">{{ t('Nobody') }}</option>
            <option value="members">{{ t('Members') }}</option>
            <option value="admins">{{ t('Administrators') }}</option>
          </select>
        </label>
      </template>

      <h3>{{ t('Recent activity') }}</h3>
      <p v-if="!log.length" class="activity__empty">
        {{ t('Nothing has happened here yet.') }}
      </p>
      <ul v-else class="activity">
        <li v-for="entry in log" :key="entry.id">
          <span class="activity__what">{{ describe(entry) }}</span>
          <span class="activity__who">
            {{ entry.actor ? entry.actor.name || entry.actor.username : t('Somebody') }}
            ·
            {{ formatDate(entry.when) }}
          </span>
        </li>
      </ul>

      <h3>{{ t('Tell me about') }}</h3>
      <p class="notify__note">
        {{
          auth.user?.email
            ? t('Sent to {email}, once a group has been quiet for a while.', {
                email: auth.user.email,
              })
            : t('Shown in your notifications. Add an email address to receive them as mail too.')
        }}
      </p>
      <ul class="notify">
        <li v-for="kind in NOTIFICATION_KINDS" :key="kind.name">
          <label>
            <input
              type="checkbox"
              :checked="open.notifications?.[kind.name] ?? false"
              @change="
                setNotification(kind.name, ($event.target as HTMLInputElement).checked)
              "
            />
            <span>{{ kind.label() }}</span>
          </label>
        </li>
      </ul>

      <h3>{{ t('Members') }}</h3>
      <ul class="members">
        <li v-for="member in open.members" :key="member.id" class="member">
          <div>
            <p class="member__name">{{ member.displayName || member.username }}</p>
            <p class="member__detail">
              {{ member.owner ? t('Owner') : member.role === 'admin' ? t('Administrator') : t('Member') }}
            </p>
          </div>
          <div class="member__actions">
            <template v-if="canAdminister && !member.owner">
              <AppButton
                variant="text"
                @click="setRole(member.id, member.role === 'admin' ? 'member' : 'admin')"
              >
                {{ member.role === 'admin' ? t('Make a member') : t('Make an administrator') }}
              </AppButton>
              <AppButton v-if="open.owner" variant="text" @click="transfer(member.id)">
                {{ t('Hand over the group') }}
              </AppButton>
              <AppButton variant="text" @click="removeMember(member.id)">{{ t('Remove') }}</AppButton>
            </template>
            <AppButton
              v-else-if="member.id === auth.user?.id && !member.owner"
              variant="text"
              @click="confirming = 'leave'"
            >
              {{ t('Leave') }}
            </AppButton>
          </div>
        </li>
      </ul>

      <p v-if="confirming === 'leave'" class="confirm" role="alert">
        <span>{{ t('Leave this group? You will lose access to its library.') }}</span>
        <span class="confirm__actions">
          <AppButton variant="text" @click="confirming = null">{{ t('Cancel') }}</AppButton>
          <AppButton @click="removeMember(auth.user!.id)">{{ t('Leave') }}</AppButton>
        </span>
      </p>

      <template v-if="canAdminister">
        <h3>{{ t('Invitations') }}</h3>
        <p class="panel__lead">
          {{ t('An invitation reaches an address rather than an account, so somebody without one here can still be asked.') }}
        </p>
        <ul v-if="open.invitations?.length" class="members">
          <li v-for="invitation in open.invitations" :key="invitation.id" class="member">
            <div>
              <p class="member__name">{{ invitation.email }}</p>
              <p class="member__detail">
                {{ invitation.role === 'admin' ? t('Administrator') : t('Member') }}
                ·
                {{ t('Expires {when}.', { when: formatDate(invitation.expires) }) }}
              </p>
            </div>
            <AppButton variant="text" @click="revoke(invitation.id)">{{ t('Withdraw') }}</AppButton>
          </li>
        </ul>
        <form class="invite" @submit.prevent="invite">
          <AppTextField v-model="inviteEmail" :label="t('Email address')" type="email" />
          <label class="choice">
            <span>{{ t('Role') }}</span>
            <select v-model="inviteRole">
              <option value="member">{{ t('Member') }}</option>
              <option value="admin">{{ t('Administrator') }}</option>
            </select>
          </label>
          <AppButton type="submit" :loading="store.busy">{{ t('Invite') }}</AppButton>
        </form>
      </template>

      <template v-if="open.owner">
        <h3>{{ t('Delete this group') }}</h3>
        <p class="panel__lead">
          {{ t('Everything in it goes with it: items, collections, tags and attachments. There is no trash around a library.') }}
        </p>
        <p v-if="confirming === 'delete'" class="confirm" role="alert">
          <span>{{ t('Delete “{name}” and everything in it?', { name: open.name }) }}</span>
          <span class="confirm__actions">
            <AppButton variant="text" @click="confirming = null">{{ t('Cancel') }}</AppButton>
            <AppButton :loading="store.busy" @click="destroy">{{ t('Delete') }}</AppButton>
          </span>
        </p>
        <AppButton v-else variant="outlined" @click="confirming = 'delete'">
          {{ t('Delete') }}
        </AppButton>
      </template>
    </div>
  </section>
</template>

<style scoped>
.groups {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-5);
}

.groups__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--md-spacing-4);
}

.groups__empty,
.groups__error,
.groups__notice {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.groups__error,
.groups__notice {
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
}

.groups__error {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}

.groups__notice {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
}

.groups__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

.card {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-1);
  width: 100%;
  padding: var(--md-spacing-4);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.card:hover {
  background: var(--md-sys-color-surface-container-high);
}

.card__title {
  font-size: var(--md-sys-typescale-title-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
}

.card__detail,
.member__detail,
.panel__lead {
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.panel {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-5);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-low);
}

.panel h2,
.panel h3 {
  margin: 0;
}

.panel h3 {
  margin-top: var(--md-spacing-4);
  font-size: var(--md-sys-typescale-title-medium-size);
  font-weight: var(--md-sys-typescale-weight-medium);
  color: var(--md-sys-color-on-surface-variant);
}

.panel__lead {
  margin: 0;
}

.panel__actions,
.member__actions,
.confirm__actions {
  display: flex;
  gap: var(--md-spacing-2);
  justify-content: flex-end;
  flex-wrap: wrap;
}

.choice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-4);
  font-size: var(--md-sys-typescale-body-medium-size);
}

.choice select {
  min-height: 40px;
  padding: 0 var(--md-spacing-3);
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
  font: inherit;
}

.choice__note {
  margin: 0;
  color: var(--md-sys-color-on-surface-variant);
  font-size: var(--md-sys-typescale-body-small-size);
}

.members {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-2);
}

.member {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-4);
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-surface-container);
  flex-wrap: wrap;
}

.member__name,
.member__detail {
  margin: 0;
}

.invite {
  display: flex;
  align-items: flex-end;
  gap: var(--md-spacing-3);
  flex-wrap: wrap;
}

.invite > :first-child {
  flex: 1 1 16rem;
}

.confirm {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--md-spacing-3);
  margin: 0;
  padding: var(--md-spacing-3) var(--md-spacing-4);
  border-radius: var(--md-sys-shape-corner-small);
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
  font-size: var(--md-sys-typescale-body-medium-size);
  flex-wrap: wrap;
}
</style>
