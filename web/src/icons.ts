/** Trusted, bundled SVG files. No server or user markup reaches this loader. */
export interface SvgIcon {
  attributes: Record<string, string>
  markup: string
  label: string
}

export function loadIcons(files: Record<string, string>): Record<string, SvgIcon> {
  return Object.fromEntries(
    Object.entries(files).map(([path, source]) => {
      const document = new DOMParser().parseFromString(source, 'image/svg+xml')
      const svg = document.documentElement
      if (svg.localName !== 'svg' || document.querySelector('parsererror')) {
        throw new Error(`Invalid icon SVG: ${path}`)
      }
      const title = svg.querySelector('title')
      const label = title?.textContent ?? ''
      title?.remove()
      const attributes = Object.fromEntries(
        Array.from(svg.attributes)
          .filter(({ name }) => !['xmlns', 'width', 'height'].includes(name))
          .map(({ name, value }) => [name, value]),
      )
      const name = path.substring(path.lastIndexOf('/') + 1).replace(/\.svg$/, '')
      return [name, { attributes, markup: svg.innerHTML, label }]
    }),
  )
}

export const CONTROL_ICONS = loadIcons(
  import.meta.glob<string>('./assets/icons/controls/*.svg', {
    query: '?raw',
    import: 'default',
    eager: true,
  }),
)
