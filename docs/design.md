# The design system

**Audience:** contributors working on the browser interface  
**You do not need this page to install, administer or use altero.**

This is the implementation reference for altero's browser UI. The short rule is: **fill groups, outline controls, hairline separates**. Shared surfaces and tokens should be reused rather than redrawn in individual components.

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
| A card, a pane, a block, a table's heading, the app bar | `surface-container` | `.card`, `.pane`, `.block`, `.table-head` |
| Inside one of those, and every toolbar | `surface-container-high` | `.card__inset`, `.toolbar` |
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
use it, the way `auth-form.css` and `dialog.css` are. A component **does not
write this rule itself**: a card that is a different height or a different grey
on one screen reads as a seam between two applications.

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

## Tables

The item list is the one thing that is not a card, and the reason is that a
fill behind a dense list tints the thing being read. What bounds it instead:

- **A filled heading strip** (`.table-head`) — the one part of a table that is
  chrome rather than content, so it takes the card's fill and rounds its top
  corners. The rule beneath it is what the rows hang from.
- **A hairline between each pair of rows, and one to close the last**
  (`.table-rows`), so the table ends rather than stops.
- **The rows themselves on the page**, which is what keeps the text on the
  surface the hover wash was measured against.

The hairline belongs to the **line** rather than to the row. A row is always the
last child of its line, whether or not a checkbox sits beside it, so a rule
drawn on the row and taken off `:last-child` is taken off every row and the
list becomes a wall of text.

**The current row** carries `.row--current`: the `secondary-container` fill, and
a `primary` bar down its leading edge. The bar is not decoration. A state told
in colour alone is told to fewer people than it needs to be, which is WCAG
1.4.1, and on a long list an edge is found faster than a wash.

## Icon buttons and toolbars

Material 3's icon button comes with a container or without one. Without one it
is a glyph on a page, and a glyph on a page says nothing about being pressable
until a pointer happens to rest on it — which a finger never does.

So the **group** carries the container. A row of icon-only controls is a
`.toolbar`: the inset fill, fully rounded, holding `.icon-button`s that stay
plain. That is the standard treatment, and it keeps a row of six tools from
becoming six filled circles competing with the content they act on.

- `.toolbar` takes `surface-container-high` wherever it sits — on the page it
  is a container inside the page, and inside a card it steps up from the card.
  One value that works in both places beats two that have to be chosen right.
- `.icon-button` is 2rem around a 1rem glyph, growing to 2.5rem where the
  pointer is coarse. `.icon-button--on` stays lit for a tool that is switched
  on, which is the only thing telling a reader it is theirs to switch off;
  `.icon-button--danger` is red at rest rather than only under a pointer, which
  a finger never produces.
- An icon button that dismisses the thing it sits in — the close on a pane —
  stands outside the toolbar, because it does not act on the contents.
- Every icon-only control carries its name twice: `aria-label`, which a screen
  reader announces, and `title`, which a pointer reveals. A control with
  neither is a rebus.

## Icons

Single-weight line glyphs on a 24-unit grid, `stroke-width: 1.5`, round caps and
joins, no fill — `web/src/items/icons.ts` and `sidebaricons.ts`. The library's
are drawn to read like the desktop client's sidebar; the ones with no
counterpart there follow the same rules so they sit with them. They are drawn
rather than copied: Zotero's assets are the client's and carry its licence.

A glyph that is the only thing in a control carries a label
(`aria-label`); one that sits beside text is `aria-hidden`, because a screen
reader saying "trash trash" is worse than silence.

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

## Accessibility

The target is **WCAG 2.2 level AA**, and the parts of it that are decisions
about design rather than about markup are settled here.

**Contrast (1.4.3, 1.4.11).** `styles/contrast.node.spec.ts` reads the tokens
and measures every pair the interface actually puts on screen: 4.5:1 for text,
3:1 for the parts of a control that identify it — its border, its focus ring,
the bar on the current row. It also holds one ordering that is not a ratio: the
current row is marked more strongly than the row under the pointer, or hovering
would look like choosing.

**Colour is never the only signal (1.4.1).** A suspended account carries the
word *Suspended*, not only a red chip. The current row carries a bar as well as
a fill. A failure carries `role="alert"` as well as an error fill. A tool that
is switched on is both lit and `aria-pressed`.

**Focus (2.4.7, 2.4.11).** One ring everywhere, `primary` at 2px with an offset
so it is not confused with a control's own border, on `:focus-visible` with a
`:focus` fallback for Safari before 15.4. The application bar is sticky, so
`html { scroll-padding-block-start: 4rem }` keeps anything scrolled into view
clear of it.

**Targets (2.5.8).** Nothing you can press is smaller than 24 by 24 CSS pixels,
and the controls a finger reaches for grow past that on a coarse pointer. The
smallest ones — a pencil on a tag, a twisty in the tree — sit at exactly 24 with
their glyphs unchanged.

**Dragging has an alternative (2.5.7).** Everything a drag of the item list can
express can also be done without one: filing and copying through **Move or
copy…**, trashing and deleting through the tools, and a collection is moved by a
picker rather than dragged at all. See
[web/library.md](web/library.md#by-touch).

**Authentication (3.3.8).** Nothing asks a reader to solve a puzzle, transcribe
an image or remember anything but their password, and nothing prevents pasting
into a field — including the one-time code.

**Motion (2.3.3).** `prefers-reduced-motion` turns the transitions off, at
0.01ms rather than zero so that a transition end event nothing else waits for
still fires.

What this cannot claim: none of it has been through a screen reader or a real
audit. The measurable parts are measured, in tests that fail; the rest is
careful work by somebody who cannot see the result. The item list is a list of
buttons rather than a `role="grid"`, so a reader hears each row's values in
order without hearing the column names — a deliberate trade, and the first
thing to revisit if this is ever tested with assistive technology.

## What keeps this

`web/src/styles/surfaces.node.spec.ts` reads every component in the tree and
fails on three things: a component that paints a surface step of its own
(`background: var(--md-sys-color-surface-container…)` outside the shared
stylesheets), anything that reaches for the steps below the page, and an area
bounded in the divider colour, which is a group drawn as an outline rather than
a fill. A control's own border in `outline` is untouched by that last rule,
which is the distinction `contrast.node.spec.ts` draws: `outline` bounds
something you can operate, `outline-variant` divides things you cannot.

Three components are listed there as exceptions, each for its own reason: the
application bar is chrome rather than a card, the theme menu floats, and the
publications dialog fills a step above the dialog it sits in. A fourth is a
deliberate line in a test rather than a CSS block somebody copied.

That is the same shape as the two guards already in `web/src/styles`:
`fonts.node.spec.ts`, which fails if a font is ever fetched from somebody else's
machine, and `contrast.node.spec.ts`, which fails if the palette stops being
readable. A design system nobody can accidentally leave is worth more than one
written down.
