# Web interface implementation notes

This reference is for contributors changing the browser interface. For user
tasks, see the [web guide](../web-interface.md).

## Building it

Built into the container image already. From a source checkout:

```sh
cd web
npm ci
npm run build        # writes into src/altero/web/static
npm test
npm run dev          # localhost:5173, proxying the API to :8000
```

Without that build the server still runs and the API is fully usable; `/app/`
answers 503 and says what to run.

## Browser support

Keep the build target at ES2020, Safari 14 (including iOS 14.6), Chrome 87,
Edge 88 and Firefox 78. Vite lowers syntax; it does not supply missing runtime methods.
Own-property checks in locale selection and the note editor therefore use
`Object.prototype.hasOwnProperty.call`, which works without `Object.hasOwn`.
Feature-detect newer platform APIs and retain the existing fallback behavior.

Browser checks remove selected APIs to exercise these paths in Chromium. They
do not establish compatibility with an actual older browser or iPhone; verify
those separately before claiming device coverage.

## End-to-end tests

`npm run e2e` drives the built interface in Chromium, at desktop and phone
sizes, against a real server on a throwaway SQLite database. It fails on any
Content-Security-Policy violation and on serious or critical axe findings.
Build first; the first run needs `npx playwright install chromium`.

Tests cover editing, merging, files, sharing, account security, translated
controls, right-to-left layout, touch and keyboard interaction, motion, and
app update behavior. Verify persisted API state as well as rendered feedback.
These Chromium checks do not establish Safari, native-device or screen-reader
compatibility, and catalog checks do not replace linguistic review.

When reopening a seeded item, use `libraryRow` or `openItem` so fixtures beyond
the first page are loaded. Scroll drag targets into view. Clean up temporary
paging and tree fixtures so a test does not depend on suite order.

## Design

Use the shared [design system](../design.md), surface classes and tokens.
Theme selection follows the operating system unless the user overrides it.
Style guards check surface use, contrast, fonts and logical CSS properties.

Fonts are self-hosted IBM Plex Sans, with Japanese, Arabic and Hebrew faces.
Use the supplied stylesheets and `font-display: swap`; script-specific sheets
load on demand. Keep package installation scripts disabled to avoid telemetry.
No font request should reach a third party.

Use logical start/end properties for right-to-left layout. Mixed-language
content determines its own direction. Verify mouse, touch and splitter-key
behavior in both directions.

Popup command menus keep their items outside the sequential tab order. Arrow
keys move inside; Tab and Shift+Tab close the menu and continue from its trigger.
Escape restores the trigger, while moving focus outside dismisses the menu
without taking focus back. The theme trigger also opens with Up/Down arrows.

Collapsible sections use `interpolate-size: allow-keywords` when available,
scoped to their active transition. Older browsers retain measured CSSOM heights.
Both paths retire departing controls, release heights after completion or
cancellation, and honor reduced motion. Browser checks exercise native and
forced measured paths, including nested branches and interrupted toggles.

Tags share `TagPill.vue`, `styles/tag-pills.css` and ordering in `items/tags.ts`.
The component owns rename drafts and errors; callers provide library filtering
or item-only removal. Pending additions and removals project over current tags
without mutating synced item versions. Queued writes rebase; a refused write
removes only its own projection. Navigation discards unsent operations.

## Durable sign-in budgets

`services/loginlimits.py` reserves an account and address allowance in
`login_attempts`. Reservations commit before verification so concurrent requests and worker restarts share a budget;
no database lock spans password hashing. Call before changing other state in
the session. Password sign-in and both TOTP/email completion paths use these
reservations; the API layer supplies the trusted connection address and maps a
refusal to JSON `429` with a whole-second `Retry-After`.

Account and address rows are locked in sorted key order on both SQLite and
PostgreSQL. A successful proof clears only its account reservation's generation
and refunds exactly one address attempt. An older success cannot erase a newer
account guess or refund a new address window after expiry. Identifiers are
SHA-256 hashes with separate namespaces; these are pseudonymous counters, not
encrypted personal data. Idle rows expire after fifteen minutes and are pruned
by the next reservation.

Username and email aliases resolve to the same user id before reserving the
password budget. Unknown identifiers use the same limits with normalized names.
TOTP and email share a second-factor budget by user id, so a new pending
session, a resend or a factor switch cannot reset it. The existing five-guess
limit on each emailed code remains in force independently.

## The note editor

The editor uses Tiptap with a port of Zotero's note schema, HTML parsing,
serialization and keymap in `web/src/notes/`. Differential checks and the
recorded corpus protect round trips with the desktop editor. Load it on demand.
Disable Tiptap's injected stylesheet for CSP compatibility; use `notes/editor.css`.

Toolbar menus use fixed viewport positions. Apply those coordinates before
moving keyboard focus into the menu: focusing the unpositioned list can scroll
the document, whose scroll handler then dismisses it. Focus also disables native
ancestor scrolling; only the menu list scrolls to reveal the selected option.
Scroll notifications dismiss the menu when its anchor moves. A notification
queued while the trigger was focused can arrive after opening and must leave
the menu open when its anchor is unchanged. The browser regression opens New
Note below a populated collection sidebar and checks that the menu stays open
without moving the page.

## Undoing filing and trash changes

`PATCH /web/libraries/{id}/items` returns an `undo` object alongside `items`.
Its `version` is the committed library watermark; its `items` hold each changed
item's prior `collections` and/or `deleted` value. Unchanged properties and
items are omitted. The snapshot comes from stored state under the write lock,
so it includes memberships the browser had not loaded.

`POST /web/libraries/{id}/items/undo` accepts that `items` array with
`If-Unmodified-Since-Version` set to the returned version. It requires the
browser session, CSRF token and current item permissions. The version must
match exactly under the write lock: a later sync, edit or undo returns 412
without changing anything. Every item is restored in one transaction and one
new library version. Only collection memberships and trash state can be
restored here; permanent deletion and merge graphs are outside this endpoint.
The browser does not persist these snapshots across page reloads.

Filing, trashing and restoring through the library store show the offer after
the write commits. A failed list refresh does not report the write as failed
or invite a second write. Undo remains bound to its original library after
navigation; an open parent's children are refreshed as well. A refusal is
reported in the toast region, with a separate message for a stale watermark.

`POST /web/libraries/{source}/items/copy` returns the same `undo` shape, with
the **destination** library version and newly created root keys set to
`deleted: true`. Send it to the destination's undo endpoint. This moves the
copies and their child graphs into its Trash without deleting their bytes or
changing the originals. A source-library edit does not invalidate this offer;
a destination edit does. The response contains `undo: null` when the caller
may copy but cannot remove records there, such as an add-only group member.
Permissions are checked again when undo runs.

## Duplicate merge endpoint

The duplicates listing accepts `grouped=true` with `scope=duplicates`. It returns
`groups` (lists of item keys), `totalGroups`, and the usual item envelopes and
library watermark. In this mode `start` and `limit` count groups. Search, tag and
collection filters find groups; every member readable by the viewer is included,
oldest first. The requested sort orders groups by their first matching record.
Without `grouped`, the existing item-based pagination is unchanged.

The export endpoint accepts the same `grouped=true` flag, expanding matching
groups before writing them in batches. Explicit group-member selections export
by key with `scope=all`, so the current search cannot remove a selected member.

The library store requests group pages and selects a whole group from any member.
Select-all stays within the active group. Explicit individual inspection remains
available, and an append at a different watermark restarts group pagination.

Groups are connected components of the existing candidate matches. A matching
identifier can connect records whose titles differ, and a title match can connect
another record to that group. Membership is a suggestion for review, not a claim
that every pair has the same identifier or item type.

The comparison follows the desktop's master-and-field-choice model, reviewed in
`duplicatesMergePane.js` and `itemBox.js`. The browser uses native select controls
instead of desktop field popups. Group selection, individual inspection and
membership changes have ordinary click/tap controls; coarse pointers retain
44-pixel targets. On a narrow screen, activating a group reveals its pane and
closing it returns focus to the group.

The duplicates pane uses
`POST /web/libraries/{id}/items/merge`, authenticated by the browser session
and CSRF token. It accepts:

```json
{
  "master": "MASTER22",
  "others": ["DUPL2345"],
  "fields": {
    "title": "Chosen title",
    "creators": [{"creatorType": "author", "name": "A collective"}]
  }
}
```

Send `If-Unmodified-Since-Version` with the library version at which the items
were read. The version must match exactly, checked under the library lock.
An absent header answers 428; a stale or future one answers 412. On 412, read
the selected items again and review the choices before retrying.

The browser prepares a separate review snapshot with `scope=all` and the selected
keys, in batches of at most 100. Every batch must report the same library version
and include every selected key. Live list refreshes do not advance that snapshot's
version. Confirmation sends it once; a failed list refresh after a committed merge
does not turn success into an invitation to submit the merge again.

The items must be untrashed regular items of one type in this library, named
once each. `fields` is optional: omitted fields and creators stay on the
master, text or null replaces a bibliographic field, and a `creators` array
replaces the whole creator list. An empty string or null clears a field;
`creators: []` clears creators. Structural properties, type changes and
timestamps are refused. Tags, collections and relations are combined by the
merge itself, including attachment deduplication and child moves, in one new
library version.

The 200 response includes `items`, with the master first and each changed
item in its ordinary envelope. `Last-Modified-Version` gives their shared new
version. An optional `locale` query selects the interface language for PDF
word ordering; it defaults to the account language, then `en-US`.

It also returns `undo: {"version": N, "merge": true}`. To reverse that merge,
send `POST /web/libraries/{id}/items/merge/undo` with the session, CSRF token and
`If-Unmodified-Since-Version: N`. The request carries no item data. A private
database snapshot holds the prior values of precisely the properties changed
by the merge, including incoming relations and attachment/annotation parents.
Only the person who merged can use it; all current item permissions apply again.

The library and stored merge versions must both match under the write lock.
A later write or retry answers 412, even if the caller supplies a newer version.
A missing, expired or another person's snapshot answers 404. Each library keeps
at most one snapshot, for five minutes; a subsequent merge replaces it. The
retention sweep removes expired snapshots, and clearing/restoring a library
removes its snapshot. Snapshots are excluded from library archives.

Undo restores the old fields, creators, tags, collections, dates added, trash
states, note HTML and relations at one **new** library version. It never rewinds
sync versions or changes registered file bytes/full text. Notes promoted from
attachment text during the merge go to Trash; their original text returns to
the attachment. A refused reversal rolls back every change and keeps the
snapshot available until it expires or the library changes.

An inverse that effectively changes only relations keeps the current
`dateModified`, as ordinary browser relationship edits do. On undeleting a
duplicate, Zotero removes its survivor's merge-tracking relation itself while
preserving that date, and can skip the now-redundant remote update. Other
restored content receives the normal new modification timestamp.

## Not built yet

Items, notes and attachments can be created and edited in the browser, and
duplicate items can be merged. Remaining browser gaps include:

- An integrated PDF reader and annotation tools.
- Offline library access. The installed app opens offline, but library data is
  not stored on the device.
- Advanced search and a saved-search builder.
- Adding items by DOI, ISBN or PMID.
- A citation-style picker and a multi-item bibliography or report interface.
  The server already renders bibliographies and reports; the detail pane's
  citation uses `format=bib`.
- Deleting a tag from the whole library at once.

Moving in from zotero.org brings the personal library only; a group has to be
made here and its members invited.

For account and server operations, see [Administration](../administration.md).
