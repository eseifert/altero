import { afterEach } from 'vitest'

import { config, enableAutoUnmount } from '@vue/test-utils'

import { i18n } from './i18n'

// Every component that renders a string uses `useI18n`, which needs the plugin
// installed. Doing it here rather than in each `mount` keeps the tests about
// what the component does rather than about how it is wired.
config.global.plugins = [i18n]

// Take each mounted component down again when its test ends. A component left
// mounted keeps its watchers and its half-finished requests, and both go on
// running during the tests that follow: a store action resolving in one of them
// makes that test's Pinia the active one, so the *next* test's `useStore()`
// hands back a store the component it just mounted has never heard of. That
// cost an afternoon; it is not a thing to rediscover.
enableAutoUnmount(afterEach)

// Vitest runs in jsdom, which implements neither of these. Both are used by
// the theme store, so without them every component test that mounts the app
// shell would fail on a missing global rather than on anything real.
//
// A test file may opt out of the DOM with `@vitest-environment node`, and this
// setup still runs for it, so there is nothing to patch.
// jsdom parses <dialog> but implements none of its behaviour, so a component
// that opens one would fail on a missing method rather than on anything real.
// The stub is only what the tests observe: whether it is open, and that closing
// it says so.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement, value?: string) {
    this.open = false
    if (value !== undefined) this.returnValue = value
    this.dispatchEvent(new Event('close'))
  }
}

if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

// jsdom implements no WebAuthn at all, and a component that merely *asks*
// whether passkeys are available would otherwise fail on a missing global
// rather than on anything real. The stub says "no" by default; a test that
// wants passkeys replaces it.
if (typeof window !== 'undefined' && window.PublicKeyCredential === undefined) {
  Object.defineProperty(window, 'PublicKeyCredential', {
    value: undefined,
    writable: true,
    configurable: true,
  })
}
