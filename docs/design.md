# The design system

What the web interface looks like, written down so it stays one interface. It
grew a seam without anyone deciding to: the settings sections drew a card as a
hairline outline with nothing behind it, the administration screens drew one as
a filled block, and three other screens picked whichever `surface-container-*`
step was nearest to hand. Every one of those was defensible on its own screen
and none of them agreed. This document is the decision, and
`web/src/styles/surfaces.node.spec.ts` is what keeps it.

Material 3 is the frame, seeded from a teal (`web/src/styles/tokens.css`), with
light and dark following the operating system unless somebody chooses. What
follows is what altero does *inside* that frame, which is where the choices are.

## The one rule

**Fill groups, outline controls, hairline separates.**

- A group of related things — a card, a panel, a callout — is marked by a
  **fill**. Never by a border.
- A **border** means something you can operate: a text field, the search box
  once it is open, a select. It is drawn in `outline`, which
  `contrast.node.spec.ts` holds to 3:1 because WCAG 1.4.11 asks that of the
  part of a control that identifies it.
- Rows *inside* a group are separated by a **hairline** in `outline-variant`,
  which is a divider and is exempt from that ratio. A hairline never bounds a
  group; it only divides one.

If a new screen needs a bounded area, it is a card. If it needs to stand out
more than that, it is not a card — it floats, and `dialog.css` already says what
that looks like.

## Surfaces, in order

The page is `surface` — white in light, near-black in dark. Everything else
steps *away* from the page in one direction, so depth reads the same in both
schemes:

| Layer | Token | Where |
| --- | --- | --- |
| The page | `surface` | behind everything |
| A card, a pane, a block, the app bar | `surface-container` | `.card`, `.pane`, `.block` |
| Inside one of those | `surface-container-high` | `.card__inset` |
| Floating | `surface-container-high` + a shadow | dialogs and menus, in `dialog.css` |

Three steps, and a component may not reach for a fourth. `surface-container-low`
and `-lowest` exist in the token file because Material defines them; the
interface does not use them — over a white page `-low` is 1.03:1, so whatever
it was meant to separate was not separated — and the guard test says so.

The other containers are not depth, they are meaning, and they keep their jobs:
`secondary-container` marks the row you have chosen, `error-container` marks
what has gone wrong or what cannot be undone, `primary` is what you are meant to
press.

## The card

```css
.card {
  display: flex;
  flex-direction: column;
  gap: var(--md-spacing-3);
  padding: var(--md-spacing-5);
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container);
}
```

It lives in `web/src/styles/surfaces.css` and is imported by the components that
use it, the way `auth-form.css` and `dialog.css` already are. A component **does
not write this rule again** — that is how the seam appeared.

- `.card__title` — the heading inside a card: `title-medium`, medium weight, no
  margin. Cards are titled by their content, not by their size.
- `.card__note` — the quiet line under a control: `body-small`,
  `on-surface-variant`. This is where an explanation goes; it is not a smaller
  paragraph of body text.
- `.card__inset` — a block inside a card that is its own thing: an API key shown
  once, a link to hand over, a warning. `surface-container-high`, corner-small.
- `.card__warning` — an inset that says what cannot be undone, in
  `error-container`. Before the button, never after it.
- `.card--interactive` — a card you can press, such as a group in the list. It
  answers the pointer with the same wash a row does.
- `.card__rows` — rows inside a card, divided by hairlines and bounded by the
  card's own edge.
- A button inside a card is as wide as its label. Stretched across the card it
  reads as the card's own edge rather than as something to press.

Two more words for things that are not cards but are painted the same:

- `.pane` — a column of a screen rather than a group on one: the item list's
  detail pane. The same fill, no opinion about padding, because a pane's
  contents arrange themselves and usually scroll.
- `.block` — one thing on a page rather than a group of them: a rendered
  citation, a note, the answer to "what would this delete". Card fill, small
  corner.
- `.chip` — a word about the thing beside it: a key's last four characters, a
  role, *Suspended*. `secondary-container`, because a chip carries meaning
  rather than depth; `.chip--warning` for what is out of service.

## The one thing that is not filled

The item list. A table is bounded by the rule under its heading and the
hairlines between its rows, and nothing else: a fill behind a dense list tints
the thing being read, and the hover wash is measured against the page it sits
on. So `.library__table` lost its outline and gained nothing in its place,
which is the same decision as filling everything else — the box was what had to
go.

## Rows

A list of things you can act on — libraries in the sidebar, sections in a panel,
accounts, groups — is rows, not cards. One row is:

- separated from the next by nothing at all, or by a hairline where the rows are
  tall enough to need it;
- `--md-sys-state-hover-surface` under the pointer, which is a translucent wash
  of the text colour rather than another surface step, so it reads the same over
  a white list as over a dialog;
- `secondary-container` when it is the current one, which is deliberately
  stronger than the hover wash: `contrast.node.spec.ts` asserts that ordering,
  because a row under the pointer that looks more chosen than the chosen row is
  a lie about where you are.

The settings panel and the administration panel are the same rows as the
library's sidebar, to the pixel, from `components/SectionPanel.vue`. Two
sidebars that differ slightly read as two applications.

## Spacing and shape

Spacing comes from `--md-spacing-1` to `-7` (4, 8, 12, 16, 24, 32, 48). Inside a
card the gap is `-3`; between cards, `-4`; a card's own padding is `-5`. A page's
sections are `-5` apart. Nothing uses a bare pixel value for space.

Corners: `corner-small` (8px) for something inside a card, `corner-medium`
(12px) for the card itself, `corner-full` for a pill or a round icon button.
`corner-large` and `-extra-large` are for dialogs.

## Type

One family, IBM Plex Sans, served by this application — see
[web-interface.md](web-interface.md#design) for why and what it costs. The scale
is in the tokens; what matters here is which step means what:

- `title-large` — the name of a screen, once.
- `title-medium` — the heading of a card.
- `body-medium` — everything you read.
- `body-small` — a note under a control, a timestamp, a count.
- `label-medium` — a chip.

Nothing sets `text-transform`, and nothing invents a size. A number that wants
to line up in a column gets `font-variant-numeric: tabular-nums`.

## Colour is not the only signal

Anything the colour says is said again in words or in shape: a suspended account
carries the word *Suspended*, not only a red chip; a failure has `role="alert"`
as well as an error fill. The palette is measured by
`styles/contrast.node.spec.ts`, which reads the tokens and checks every pair the
interface actually puts on screen — 4.5:1 for text, 3:1 for the parts of a
control that identify it.

## Icons

Single-weight line glyphs on a 24-unit grid, `stroke-width: 1.5`, round caps and
joins, no fill — `web/src/items/icons.ts` and `sidebaricons.ts`. The library's
are drawn to read like the desktop client's sidebar; the ones with no
counterpart there follow the same rules so they sit with them. They are drawn
rather than copied: Zotero's assets are the client's and carry its licence.

A glyph that is the only thing in a control carries a label
(`aria-label`); one that sits beside text is `aria-hidden`, because a screen
reader saying "trash trash" is worse than silence.

## What keeps this from drifting again

`web/src/styles/surfaces.node.spec.ts` reads every component in the tree and
fails on three things: a component that paints a surface step of its own
(`background: var(--md-sys-color-surface-container…)` outside the shared
stylesheets), anything that reaches for the steps below the page, and an area
bounded in the divider colour — the outlined card this replaced. A control's own
border in `outline` is untouched by that last rule, which is the distinction
`contrast.node.spec.ts` already draws: `outline` bounds something you can
operate, `outline-variant` divides things you cannot.

Three components are listed there as exceptions, each a different one: the
application bar is chrome rather than a card, the theme menu floats, and the
publications dialog fills a step above the dialog it sits in. Adding a fourth is
a deliberate line in a test rather than a CSS block somebody copied.

That is the same shape as the two guards already in `web/src/styles`:
`fonts.node.spec.ts`, which fails if a font is ever fetched from somebody else's
machine, and `contrast.node.spec.ts`, which fails if the palette stops being
readable. A design system nobody can accidentally leave is worth more than one
written down.
