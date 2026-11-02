# Web interface implementation notes

This page covers how the browser interface is built, how it is styled, and what it does not do yet.

## Common tasks

- Build the Vue application from `web/` when running from source.
- Use the shared design system rather than introducing one-off component styling.
- Check the known-gap list before implementing a browser feature that may already be intentionally out of scope.

## Detailed behavior

The sections below retain the technical and behavioral detail needed for troubleshooting and development. You can stop after the task summary if you only need to use the feature.

### Building it

Built into the container image already. From a source checkout:

```sh
cd web
npm install
npm run build        # writes into src/altero/web/static
npm test
npm run dev          # localhost:5173, proxying the API to :8000
```

Without that build the server still runs and the API is fully usable; `/app/`
answers 503 and says what to run.

### End-to-end tests

`npm run e2e` drives the built interface in Chromium, at desktop and phone
sizes, against a real server on a throwaway SQLite database. It fails on any
Content-Security-Policy violation and on serious or critical axe findings.
Build first; the first run needs `npx playwright install chromium`.

### Design

The design follows Material 3 with a teal accent, and light and dark follow the
operating system unless the user picks one. What altero does inside that frame
is written down in [design.md](../design.md): one rule — fill groups, outline
controls, hairline separates — three surface steps, one card recipe that every
screen imports rather than draws itself, and a toolbar around every row of
icon-only tools, because a glyph on a page says nothing about being pressable
until a pointer rests on it. `styles/surfaces.node.spec.ts` fails when a
component draws a surface of its own.

The target is WCAG 2.2 AA. What can be measured is measured in tests that fail
— every contrast pair the interface puts on screen, and the ordering that keeps
a hovered row from looking more chosen than a chosen one — and
[design.md](../design.md#accessibility) says which criteria were decided where,
including what has not been verified.

Hover is a state layer rather than a color — a translucent wash of the text
color, one token, laid over whatever is underneath. One wash rather than a
surface step per depth: it reads the same over the item list as over a dialog's
raised surface, where a step chosen to separate a row from a white page comes
to 1.03:1 and a screen at an angle shows nothing at all.
`styles/contrast.node.spec.ts` measures what the wash comes to on each surface
it lands on, and checks the one ordering that matters: a selected row is marked
more strongly than the row under the pointer, or hovering would look like
choosing.

It is set in IBM Plex Sans, with Plex Sans JP for Japanese, Plex Sans Arabic
for Arabic, Persian, Urdu and Shahmukhi Punjabi, and Plex Sans Hebrew for Hebrew.
All are served by this application: no CDN or other third party receives a
font request. The Latin and Japanese faces are split by `unicode-range`, so a
page fetches only the subsets its text needs. The Arabic and Hebrew packages
provide complete faces; regular, medium and bold are included, with italic
synthesized by the browser. Their stylesheets are deferred alongside Japanese,
and font files are fetched only when text needs them, including mixed-language
libraries. Every face uses `font-display: swap`, so system fonts show the text
while it loads. Fingerprinted assets are cached for later visits. Package
installation scripts remain disabled to prevent IBM's telemetry hook.

The RTL checks cover Arabic screenshots and axe on desktop and phone, mixed
item and note directions in both UI directions, public profiles and shares,
splitter keys, mouse drags and touch holds. Font checks inspect the faces that
Chromium actually used to draw every script letter in the five RTL catalogues.
These are Chromium checks at two viewport sizes; Safari and native-device
verification remain separate.
Mirroring uses composed transforms and ancestor selectors compatible with the
build's browser targets. A compiled-selector check keeps scoped CSS from
applying a splitter transform to the document itself.

### Durable sign-in budgets

`services/loginlimits.py` reserves an account and address allowance in
`login_attempts`, introduced by migration `ae39b4d8c021`. Reservations commit
before verification so concurrent requests and worker restarts share a budget;
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

### The note editor

Notes are edited with Tiptap over a port of Zotero's own note-editor schema
(`web/src/notes/`), so a note saved here is the HTML Zotero Desktop would save:
the specs, the HTML reading and writing and the keymap are the original's, and
a differential run against the original code at the revision Zotero pins found
no difference. `web/src/notes/corpus/` holds notes as Zotero 10.0.6's shipped
editor saved them, recorded by the `note-corpus` desktop acceptance scenario,
and the editor here is tested to save each the same way. The editor is loaded the first time a note is opened. Tiptap's
injected stylesheet is switched off, because the interface's
Content-Security-Policy refuses inline styles; `notes/editor.css` carries it.

Toolbar menus use fixed viewport positions. Apply those coordinates before
moving keyboard focus into the menu: focusing the unpositioned list can scroll
the document, whose scroll handler then dismisses it. Focus also disables native
ancestor scrolling; only the menu list scrolls to reveal the selected option.
Scroll notifications dismiss the menu when its anchor moves. A notification
queued while the trigger was focused can arrive after opening and must leave
the menu open when its anchor is unchanged. The browser regression opens New
Note below a populated collection sidebar and checks that the menu stays open
without moving the page.

### Undoing filing and trash changes

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

### Duplicate merge endpoint

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

The comparison follows Zotero 10.0.6's master-and-field-choice model, reviewed in
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

The 200 response is `{"items": [...]}`, with the master first and each changed
item in its ordinary envelope. `Last-Modified-Version` gives their shared new
version. An optional `locale` query selects the interface language for PDF
word ordering; it defaults to the account language, then `en-US`.

### Not built yet

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

Making an account for somebody else, resetting a password, suspending an
account and the operator's view of the instance are under **Administration**
above. [administration.md](../administration.md) says what the shell covers alone
and what it shares with the browser.
