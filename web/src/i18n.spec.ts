import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Production catalogs are deliberately absent from these behavior tests.
vi.mock('./locales/en-US', () => ({ default: {
  greeting: 'base {person}', fallback: 'fallback {value}', count: '{count} A | {count} B',
} }))

const textInfo = Object.getOwnPropertyDescriptor(Intl.Locale.prototype, 'getTextInfo')

let subject: typeof import('./i18n')
let release: () => void
let ready: Promise<void>
let fetched: ReturnType<typeof vi.fn<() => void>>

beforeEach(async () => {
  vi.resetModules()
  ready = new Promise<void>((resolve) => { release = resolve })
  fetched = vi.fn<() => void>()
  vi.doMock('./locales/fr', async () => {
    fetched()
    await ready
    return { default: { greeting: 'fixture {person}' } }
  })
  vi.doMock('./locales/de', () => ({ default: { greeting: 'other {person}' } }))
  vi.doMock('./locales/ar', () => ({ default: { greeting: 'rtl {person}' } }))
  vi.doMock('./locales/pl', () => ({ default: { count: '{count} A | {count} B | {count} C' } }))
  subject = await import('./i18n')
})

afterEach(() => {
  release()
  vi.restoreAllMocks()
  if (textInfo) Object.defineProperty(Intl.Locale.prototype, 'getTextInfo', textInfo)
  else Reflect.deleteProperty(Intl.Locale.prototype, 'getTextInfo')
  document.documentElement.lang = 'en-US'
  document.documentElement.dir = 'ltr'
})

describe('locale resolution', () => {
  it('uses account preference, then supported browser languages, then the default', () => {
    expect(subject.resolveLocale('ja', ['de-AT'])).toBe('ja')
    expect(subject.resolveLocale('unsupported', ['cy', 'fr-CA', 'de'])).toBe('fr')
    expect(subject.resolveLocale(null, ['cy', 'kl'])).toBe('en-US')
    expect(subject.isLocale(null)).toBe(false)
    expect(subject.isLocale('unsupported')).toBe(false)
    expect(subject.isLocale('fr')).toBe(true)
  })

  it.each([
    ['DE_at', 'de'], ['pt_br', 'pt-BR'], ['en', 'en-US'],
    ['en-AU', 'en-GB'], ['en-CA', 'en-US'], ['zh-Hant', 'zh-TW'],
    ['zh-Hans-TW', 'zh-CN'], ['he', 'he-IL'], ['no-NO', 'nb'], ['fil-PH', 'tl'],
    ['pa-PK', 'pa-Arab'], ['pa-Arab-IN', 'pa-Arab'],
    ['pa-Guru-PK', null], ['pa', null], ['kl-GL', null],
  ])('normalizes %s to %s', (tag, expected) => {
    expect(subject.matchLocale(tag)).toBe(expected)
  })
})

describe('loading and switching', () => {
  it('loads on demand, caches the catalog and leaves the active locale alone', async () => {
    expect(fetched).not.toHaveBeenCalled()
    expect(subject.i18n.global.availableLocales).toEqual(['en-US'])
    const loading = subject.loadLocale('fr')
    await vi.waitFor(() => expect(fetched).toHaveBeenCalledOnce())
    expect(subject.i18n.global.getLocaleMessage('fr')).toEqual({})
    release()
    await loading
    expect(subject.i18n.global.getLocaleMessage('fr')).toEqual({ greeting: 'fixture {person}' })
    expect(subject.i18n.global.locale.value).toBe('en-US')
    const install = vi.spyOn(subject.i18n.global, 'setLocaleMessage')
    await subject.loadLocale('fr')
    expect(install).not.toHaveBeenCalled()
    expect(fetched).toHaveBeenCalledOnce()
  })

  it('waits for the catalog before changing messages and the document language', async () => {
    const switching = subject.setLocale('fr')
    await vi.waitFor(() => expect(fetched).toHaveBeenCalledOnce())
    expect(subject.i18n.global.locale.value).toBe('en-US')
    expect(document.documentElement.lang).toBe('en-US')
    release()
    await switching
    expect(subject.i18n.global.locale.value).toBe('fr')
    expect(document.documentElement.lang).toBe('fr')
    expect(subject.t('greeting', { person: 'Ada' })).toBe('fixture Ada')
  })

  it('keeps a later switch when an earlier fetch finishes last', async () => {
    const earlier = subject.setLocale('fr')
    await vi.waitFor(() => expect(fetched).toHaveBeenCalledOnce())
    await subject.setLocale('de')
    release()
    await earlier
    expect(subject.i18n.global.locale.value).toBe('de')
    expect(document.documentElement.lang).toBe('de')
  })

  it('preserves the active locale when a catalog cannot load and permits retry', async () => {
    vi.doMock('./locales/de', () => { throw new Error('offline') })
    await expect(subject.setLocale('de')).rejects.toThrow()
    expect(subject.i18n.global.locale.value).toBe('en-US')
    vi.doMock('./locales/de', () => ({ default: { greeting: 'recovered' } }))
    await subject.setLocale('de')
    expect(subject.t('greeting')).toBe('recovered')
  })

  it('sets and resets direction when text-info support is unavailable', async () => {
    Object.defineProperty(Intl.Locale.prototype, 'getTextInfo', {
      configurable: true, value: undefined,
    })
    await subject.setLocale('ar')
    expect(document.documentElement.dir).toBe('rtl')
    await subject.setLocale('de')
    expect(document.documentElement.dir).toBe('ltr')
  })

  it('uses browser text information when available', async () => {
    const getTextInfo = vi.fn(function (this: Intl.Locale) {
      expect(this.baseName).toBe('en-US')
      return { direction: 'rtl' }
    })
    Object.defineProperty(Intl.Locale.prototype, 'getTextInfo', {
      configurable: true, value: getTextInfo,
    })
    await subject.setLocale('en-US')
    expect(getTextInfo).toHaveBeenCalledOnce()
    expect(document.documentElement.dir).toBe('rtl')
  })

  it('uses its fallback when browser text information has no direction', async () => {
    Object.defineProperty(Intl.Locale.prototype, 'getTextInfo', {
      configurable: true, value: () => ({ direction: undefined }),
    })
    await subject.setLocale('ar')
    expect(document.documentElement.dir).toBe('rtl')
  })

  it('interpolates fallback messages and renders unknown keys as themselves', async () => {
    release()
    await subject.setLocale('fr')
    expect(subject.t('fallback', { value: 7 })).toBe('fallback 7')
    expect(subject.t('unknown')).toBe('unknown')
    expect(subject.i18n.global.t('count', 2)).toBe('2 B')
  })

  it('registers custom plural selection on the application translator', async () => {
    await subject.setLocale('pl')
    expect(subject.i18n.global.t('count', 2)).toBe('2 B')
    expect(subject.i18n.global.t('count', 5)).toBe('5 C')
  })
})
