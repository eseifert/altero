// Vitest runs in jsdom, which implements neither of these. Both are used by
// the theme store, so without them every component test that mounts the app
// shell would fail on a missing global rather than on anything real.
//
// A test file may opt out of the DOM with `@vitest-environment node`, and this
// setup still runs for it, so there is nothing to patch.
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
