# The design system

For contributors styling the browser interface. Reuse shared tokens and styles
from `web/src/styles/` rather than defining a separate visual language per component.

## The one rule

**Fill groups, outline controls, use hairlines between rows.**

- Cards, panels and callouts use a background fill without an enclosing border.
- Operable controls use the `outline` color for boundaries.
- Internal dividers use `outline-variant`; they do not enclose groups.

Use `dialog.css` for floating menus and dialogs.

## Surfaces, in order

| Layer | Token | Shared class |
| --- | --- | --- |
| Page | `surface` | Page background |
| Card, pane, block or table heading | `surface-container` | `.card`, `.pane`, `.block`, `.table-head` |
| Inset or toolbar | `surface-container-high` | `.card__inset`, `.toolbar` |
| Floating menu or dialog | `surface-container-high` with shadow | Rules in `dialog.css` |

Do not use `surface-container-low` or `-lowest`. Use `secondary-container` for
selection, `error-container` for errors and destructive warnings, and `primary`
for the main action.

## The card

Import `surfaces.css` and use `.card`. Its shared recipe defines padding,
spacing, rounding and fill.

| Class | Purpose |
| --- | --- |
| `.card__title` | Card heading |
| `.card__note` | Supporting text below a control |
| `.card__inset` | Nested content such as a newly issued key |
| `.card__warning` | Destructive warning, placed before its action |
| `.card--interactive` | A card that acts as a control |
| `.card__rows` | Rows separated by hairlines |
| `.pane` | A screen column whose contents arrange their own spacing |
| `.block` | A single content block such as a citation |
| `.chip` | A role or short status; use `--warning` for an unavailable state |

Buttons within cards fit their labels rather than stretching across the card.

## Tables

Use a filled `.table-head` above rows on the page surface. `.table-rows`
provides internal and closing hairlines. Put the divider on the line wrapper,
so rows with checkboxes retain it.

Mark the current row with `.row--current`: selection fill and a bar on the
leading edge. Selection must remain stronger than hover and recognizable
without color alone.

## Icon buttons and toolbars

Group related icon actions in `.toolbar`, with plain `.icon-button` controls.
A close button for the surrounding pane stays outside its content toolbar.

Use `--on` for an active toggle and `--danger` for destructive actions.
Every icon-only control needs `aria-label` and `title`. Decorative icons beside
text use `aria-hidden`.

## Icons

Edit SVG assets in `web/src/assets/icons/`: `items/`, `sidebar/` and `controls/`.
Use a 24-unit grid, rounded caps and joins, no fill, and the established stroke
weight. Preserve `viewBox`, `currentColor` and descriptive `<title>` elements.
Components set the display size.

Use the shared pencil for editing. Logos and favicons live separately in
`web/src/assets/`.

## Rows

Use rows for navigation and actionable lists. Reuse `SectionPanel.vue` for
settings and administration panels. Hover uses the shared translucent state
layer; current rows use the selection fill.

Collection and tag counts use `count-badge`, with tabular digits and a neutral
fill distinct from selection.

## Spacing and shape

Use `--md-spacing-1` through `-7`: 4, 8, 12, 16, 24, 32 and 48 pixels.
Card gaps use `-3`, space between cards uses `-4`, and card padding and page
section gaps use `-5`.

Use `corner-small` for insets, `corner-medium` for cards, `corner-full` for
pills, and the larger shared corners for dialogs.

## Type

Use the self-hosted IBM Plex fonts and shared type scale:

| Token | Use |
| --- | --- |
| `title-large` | Screen title |
| `title-medium` | Card title |
| `body-medium` | Body text |
| `body-small` | Supporting text, timestamps and counts |
| `label-medium` | Chips |

Avoid custom sizes and text transforms. Use `font-variant-numeric: tabular-nums`
for aligned numbers. See [font loading](web/implementation.md#design).

## Accessibility

The target is WCAG AA. The checks below cover measurable parts; the interface
has not had a full accessibility audit or screen-reader verification.

- **Contrast:** at least 4.5:1 for text and 3:1 for identifying control boundaries and focus indicators.
- **Status:** accompany color with text, shape or semantics. Errors use `role="alert"`; toggles use `aria-pressed`.
- **Focus:** use the shared visible ring. Keep focused content clear of the sticky header and restore focus after closing dialogs.
- **Targets:** at least 24 by 24 CSS pixels; grow touch controls for coarse pointers.
- **Alternatives:** provide controls for every drag operation. Use logical start/end CSS so direction changes work.
- **Authentication:** permit pasting, including into one-time-code inputs. Do not add puzzles or transcription tasks.
- **Motion:** use shared transitions in `motion.css` and respect `prefers-reduced-motion`. Press feedback must not move its target.
- **Messages:** keep toast announcements in a persistent live region. Pause expiry while pointer or keyboard focus is on the toast, independently.

Loading skeletons follow the list's structure and accompany an accessible status
message. Undo messages supplement Trash/Restore; they are not the only way to
recover a trashed item.

The item list uses buttons rather than a grid, so screen readers hear values
without column names. Review this tradeoff during assistive-technology testing.

## What keeps this

| Check | Protects |
| --- | --- |
| `surfaces.node.spec.ts` | Shared surfaces, allowed layers and divider use |
| `contrast.node.spec.ts` | Text/control contrast and selection stronger than hover |
| `fonts.node.spec.ts` | Self-hosted fonts |
| `logical.node.spec.ts` | Logical CSS properties; existing physical declarations may only decrease |
| Browser tests with axe | Serious and critical findings at desktop and phone sizes |

Review explicit guard exceptions before adding one. Passing automated checks
does not establish complete accessibility or support in every browser.
