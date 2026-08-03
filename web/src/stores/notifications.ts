import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { request } from '@/api/client'

export interface NotificationEntry {
  id: number
  kind: string
  subject: string
  body: string
  invitationId: number | null
  created: string
  read: boolean
}

export interface InvitationEntry {
  id: number
  libraryId: number
  libraryName: string
  role: string
  invitedBy: string
  status: string
  created: string
  expires: string
}

interface Payload {
  unread: number
  notifications: NotificationEntry[]
  invitations: InvitationEntry[]
}

/**
 * What is waiting for the signed-in person.
 *
 * Invitations come back alongside the notifications rather than being derived
 * from them: a notice is a record of something that happened and is never
 * rewritten, while an invitation has a live status that can change from under
 * it. Reading the two separately is what keeps a stale notice from offering an
 * Accept button for something already answered elsewhere.
 */
export const useNotificationStore = defineStore('notifications', () => {
  const notifications = ref<NotificationEntry[]>([])
  const invitations = ref<InvitationEntry[]>([])
  const unread = ref(0)
  const busy = ref(false)
  const error = ref<string | null>(null)

  const hasUnread = computed(() => unread.value > 0)

  async function load(): Promise<void> {
    busy.value = true
    try {
      const payload = await request<Payload>('/web/notifications')
      notifications.value = payload.notifications
      invitations.value = payload.invitations
      unread.value = payload.unread
      error.value = null
    } catch (thrown) {
      // The panel is secondary to whatever the person came here to do, so a
      // failure to load it must not take the page with it.
      error.value = thrown instanceof Error ? thrown.message : String(thrown)
    } finally {
      busy.value = false
    }
  }

  async function markAllRead(): Promise<void> {
    await request('/web/notifications/read-all', { method: 'POST' })
    notifications.value = notifications.value.map((entry) => ({ ...entry, read: true }))
    unread.value = 0
  }

  async function markRead(id: number): Promise<void> {
    await request(`/web/notifications/${id}/read`, { method: 'POST' })
    const entry = notifications.value.find((candidate) => candidate.id === id)
    if (entry && !entry.read) {
      entry.read = true
      unread.value = Math.max(0, unread.value - 1)
    }
  }

  async function answer(id: number, decision: 'accept' | 'decline'): Promise<void> {
    error.value = null
    try {
      await request(`/web/invitations/${id}/${decision}`, { method: 'POST' })
    } catch (thrown) {
      error.value = thrown instanceof Error ? thrown.message : String(thrown)
      throw thrown
    }
    // Reloaded rather than patched in place: accepting changes the set of
    // libraries and marks its notice read server-side, and guessing at both
    // here is how the two drift apart.
    await load()
  }

  function reset(): void {
    notifications.value = []
    invitations.value = []
    unread.value = 0
    error.value = null
  }

  return {
    notifications,
    invitations,
    unread,
    busy,
    error,
    hasUnread,
    load,
    markRead,
    markAllRead,
    answer,
    reset,
  }
})
