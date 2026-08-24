# Web interface implementation notes

This page contains build, design and known-gap information for contributors. It is not required for ordinary use of altero.

**Audience:** contributors

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

Hover is a state layer rather than a colour — a translucent wash of the text
colour, one token, laid over whatever is underneath. One wash rather than a
surface step per depth: it reads the same over the item list as over a dialog's
raised surface, where a step chosen to separate a row from a white page comes
to 1.03:1 and a screen at an angle shows nothing at all.
`styles/contrast.node.spec.ts` measures what the wash comes to on each surface
it lands on, and checks the one ordering that matters: a selected row is marked
more strongly than the row under the pointer, or hovering would look like
choosing.

It is set in IBM Plex Sans, with IBM Plex Sans JP behind it for Japanese, and
both are served by this application: nothing is loaded from a third party, no
CDN, no request that tells anyone else who is reading. The faces are split by
`unicode-range`, so a page fetches only the subsets its text needs — some 60 kB
for a European language, about 1 MB the first time somebody reads Japanese —
and the system stack shows the words while that happens. Fingerprinted assets
are cached for good, so the second visit fetches none of it.

### Not built yet

Editing an item's fields — with one exception, the Rights field, because a
licence set when a work was published has to be revisable by whoever set it.
Collections can be made, renamed, moved and removed, an item can be filed,
trashed, restored, deleted, copied to another library, published to My
Publications and written out as a file, a tag can be renamed, and a whole
library can be restored from an archive or copied in from zotero.org — but no
item's title, creators or dates can be changed here, no item can be created, and
a tag cannot be deleted or put on something. Moving in from zotero.org brings
the personal library only; a group has to be made here and its members invited.

The two things the desktop client does with a set of items that this does not
are the ones that produce a document rather than a file: Create Bibliography
from Items…, which needs a citation style chosen out of thousands, and Generate
Report…. The server renders both — `format=bib` is what the detail pane's
citation comes from — so what is missing is the asking, not the writing.

Making an account for somebody else, resetting a password, suspending an
account and the operator's view of the instance are under **Administration**
above. [administration.md](../administration.md) says what the shell covers alone
and what it shares with the browser.
