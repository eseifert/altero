import type { CreatorEntry, ItemEnvelope } from '@/stores/library'
import type { TypeOutline } from './labels'

export type MergeValue = string | CreatorEntry[]
export interface MergeField { name: string; values: MergeValue[] }

/** The desktop starts with the oldest item. Never rearrange the live list. */
export function oldestFirst(items: readonly ItemEnvelope[]): ItemEnvelope[] {
  return [...items].sort((a, b) => {
    const date = (item: ItemEnvelope) => Date.parse(String(item.data.dateAdded ?? '')) || 0
    return date(a) - date(b) || a.key.localeCompare(b.key)
  })
}

export function mergeValue(item: ItemEnvelope, name: string): MergeValue {
  if (name !== 'creators') return String(item.data[name] ?? '')
  return (item.data.creators as CreatorEntry[] | undefined ?? []).map((creator) =>
    creator.name !== undefined
      ? { creatorType: creator.creatorType, name: creator.name }
      : { creatorType: creator.creatorType, firstName: creator.firstName ?? '', lastName: creator.lastName ?? '' },
  )
}

/** Schema fields only; dates and structural properties never become choices. */
export function mergeFields(items: readonly ItemEnvelope[], outline: TypeOutline): MergeField[] {
  const names = [...outline.fields.filter((name) => name !== 'accessDate'), 'creators']
  return names.flatMap((name) => {
    const distinct = new Map<string, MergeValue>()
    for (const item of items) {
      const value = mergeValue(item, name)
      distinct.set(JSON.stringify(value), value)
    }
    return distinct.size > 1 ? [{ name, values: [...distinct.values()] }] : []
  })
}
