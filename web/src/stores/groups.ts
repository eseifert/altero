import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError, request } from '@/api/client'

/** What one member of a group may do. */
export type Role = 'member' | 'admin'

export interface GroupMember {
  id: number
  username: string
  displayName: string
  role: Role
  owner: boolean
}

export interface PendingInvitation {
  id: number
  email: string
  role: Role
  expires: string
}

/** What a group can tell a member about, and whether it does. */
export interface GroupNotifications {
  itemsChanged: boolean
  itemsDeleted: boolean
  membersChanged: boolean
  collectionsChanged: boolean
}

/** One of the four kinds, for addressing a single toggle. */
export type NotificationKind = keyof GroupNotifications

export interface Group {
  /** Internal library id, which is what every /web endpoint is addressed by. */
  id: number
  /** The id a sync client sees in /groups/<id>. */
  groupId: number
  name: string
  description: string
  type: 'Private' | 'PublicOpen' | 'PublicClosed'
  libraryReading: 'members' | 'all'
  libraryEditing: 'members' | 'admins'
  fileEditing: 'none' | 'members' | 'admins'
  version: number
  /** What this account may do here, decided by the server. */
  role: Role
  owner: boolean
  ownerId: number
  numMembers: number
  numItems: number
  members?: GroupMember[]
  invitations?: PendingInvitation[]
  /** What this account asked to hear about here. Absent until a group has
   * been read on its own; the listing does not carry it. */
  notifications?: GroupNotifications
}

export interface GroupDraft {
  name: string
  description?: string
  type?: Group['type']
  libraryReading?: Group['libraryReading']
  libraryEditing?: Group['libraryEditing']
  fileEditing?: Group['fileEditing']
}

/**
 * The groups this account belongs to.
 *
 * Nothing here decides what the person may do: every group carries the role
 * the server resolved, and the screens read that. Working it out in the
 * browser would mean a second implementation of the permission rules, drifting
 * against the one that actually refuses the request.
 */
export const useGroupStore = defineStore('groups', () => {
  const groups = ref<Group[]>([])
  const busy = ref(false)
  const error = ref<string | null>(null)
  /** Set after an action that succeeded, for the screen to acknowledge. */
  const notice = ref<string | null>(null)

  const hasGroups = computed(() => groups.value.length > 0)

  function message(thrown: unknown): string {
    return thrown instanceof ApiError ? thrown.message : String(thrown)
  }

  /**
   * Run one action, recording how it went.
   *
   * The outcome is reported rather than thrown: every screen reads `error`,
   * and a store that threw would leave each caller to remember a try/catch.
   * Whether it succeeded has to be said explicitly, because most of these
   * requests answer 204 and `undefined` is not a failure.
   */
  async function attempt<T>(
    work: () => Promise<T>,
    success?: string,
  ): Promise<{ ok: true; value: T } | { ok: false }> {
    busy.value = true
    error.value = null
    notice.value = null
    try {
      const value = await work()
      if (success) {
        notice.value = success
      }
      return { ok: true, value }
    } catch (thrown) {
      error.value = message(thrown)
      return { ok: false }
    } finally {
      busy.value = false
    }
  }

  /**
   * Refetch the list, leaving whatever message is on screen alone.
   *
   * Every write ends by reloading, and going through `attempt` for that would
   * clear the notice or the failure the write had just set -- so "Group
   * created." never appeared, and neither did the reason one was not.
   */
  async function refresh(): Promise<void> {
    try {
      groups.value = (await request<{ groups: Group[] }>('/web/groups')).groups
    } catch (thrown) {
      error.value = message(thrown)
    }
  }

  async function load(): Promise<void> {
    busy.value = true
    error.value = null
    notice.value = null
    try {
      await refresh()
    } finally {
      busy.value = false
    }
  }

  async function read(id: number): Promise<Group | null> {
    const outcome = await attempt(() => request<Group>(`/web/groups/${id}`))
    return outcome.ok ? outcome.value : null
  }

  async function create(draft: GroupDraft, success: string): Promise<Group | null> {
    const outcome = await attempt(
      () => request<Group>('/web/groups', { method: 'POST', body: draft }),
      success,
    )
    if (!outcome.ok) {
      return null
    }
    await refresh()
    return outcome.value
  }

  async function update(id: number, draft: Partial<GroupDraft>, success: string): Promise<void> {
    const outcome = await attempt(
      () => request(`/web/groups/${id}`, { method: 'PATCH', body: draft }),
      success,
    )
    if (outcome.ok) {
      await refresh()
    }
  }

  async function remove(id: number, success: string): Promise<void> {
    const outcome = await attempt(() => request(`/web/groups/${id}`, { method: 'DELETE' }), success)
    if (outcome.ok) {
      await refresh()
    }
  }

  async function setRole(id: number, memberId: number, role: Role): Promise<void> {
    await attempt(() =>
      request(`/web/groups/${id}/members/${memberId}`, { method: 'PUT', body: { role } }),
    )
  }

  async function removeMember(id: number, memberId: number): Promise<void> {
    const outcome = await attempt(() =>
      request(`/web/groups/${id}/members/${memberId}`, { method: 'DELETE' }),
    )
    if (outcome.ok) {
      await refresh()
    }
  }

  async function transfer(id: number, memberId: number, success: string): Promise<void> {
    await attempt(
      () => request(`/web/groups/${id}/transfer`, { method: 'POST', body: { userID: memberId } }),
      success,
    )
  }

  async function invite(id: number, email: string, role: Role, success: string): Promise<void> {
    await attempt(
      () => request(`/web/libraries/${id}/invitations`, { method: 'POST', body: { email, role } }),
      success,
    )
  }

  /**
   * Turn one kind of notification on or off for this account in one group.
   *
   * Sends only the toggle that moved. The server treats an omitted kind as
   * unchanged, so two tabs open on the same group cannot undo each other's
   * choices, and a stale panel cannot revert a setting it never showed.
   */
  async function setNotification(
    id: number,
    kind: NotificationKind,
    wanted: boolean,
    success?: string,
  ): Promise<void> {
    const outcome = await attempt(
      () =>
        request<GroupNotifications>(`/web/groups/${id}/notifications`, {
          method: 'PUT',
          body: { [kind]: wanted },
        }),
      success,
    )
    if (!outcome.ok) {
      return
    }
    // The server's answer rather than what was asked for: it is the whole set,
    // so a toggle changed elsewhere shows up here too.
    const group = groups.value.find((held) => held.id === id)
    if (group) {
      group.notifications = outcome.value
    }
  }

  async function revokeInvitation(invitationId: number): Promise<void> {
    await attempt(() => request(`/web/invitations/${invitationId}`, { method: 'DELETE' }))
  }

  function reset(): void {
    groups.value = []
    error.value = null
    notice.value = null
  }

  return {
    groups,
    busy,
    error,
    notice,
    hasGroups,
    load,
    read,
    create,
    update,
    remove,
    setRole,
    removeMember,
    transfer,
    invite,
    revokeInvitation,
    setNotification,
    reset,
  }
})
