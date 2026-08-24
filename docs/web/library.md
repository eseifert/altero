# Browsing and organizing a library

The browser interface is a companion to Zotero Desktop. It lets you browse, search and organize a library, but it is not intended to replace the desktop editor for bibliographic fields.

**Audience:** Zotero users

## Common tasks

- Browse collections, tags and search results from the library view.
- Create, rename, move and remove collections.
- File, trash, restore, delete or copy items without editing their bibliographic fields.
- Rename tags across a library.
- Use the same actions with mouse, keyboard or touch where the interface provides them.

## Detailed behavior

The sections below retain the technical and behavioral detail needed for troubleshooting and development. You can stop after the task summary if you only need to use the feature.

### Browsing a library

Three panes, as the desktop client has: what to show on the left, the items in
the middle, the selected item on the right.

The left is arranged as Zotero's own web library is, because somebody arriving
from zotero.org should not have to learn a second arrangement of the same
library. The personal library is **My Library** whatever the account is called
— the row is the library, not its owner — and under it hang its collections,
nested and expandable, then **My Publications**, then the **Trash**. Group
libraries follow under a heading of their own, and a group has no My
Publications, because publishing is something an account does with its own
library.

Beside those are the three rows the desktop client has and the web library does
not: **Recently Read** above the collections, **Duplicate Items** and **Unfiled
Items** below them, in the client's own order. None of the three is a scope the
v3 API has — the client works each of them out in the copy of the library it
holds — so altero answers them from the library itself, for the browser only,
and [compatibility.md](../compatibility.md#the-desktop-clients-three-extra-views)
says what each one was taken to mean. The window Recently Read covers is a
guess, and is marked as one there.

The library's row *is* the whole library: pressing it shows everything at the
top level, which is also how to get back out of a collection. There is no
second row under the library for that, and none called "Everything" covering
child notes and attachments: neither the desktop client nor the web library has
either, and the row they would duplicate is already there.

Under all of it is the tag list; picking tags narrows the middle pane, and
picking several requires all of them.

How wide the outer two columns are is the reader's to decide. Both divides can
be dragged, and moved with the arrow keys once one has the focus — `Home` and
`End` go to the extremes it will take, and a double-click puts it back where it
started. Neither has a right answer to impose: a collection tree indents per
level and a name is as long as whoever wrote it made it, and the detail pane
holds three fields for a book and six hundred words of abstract for an article.
The arrow keys move the divide rather than the pane, so `ArrowRight` always
moves it rightwards — which widens the sidebar and narrows the item detail.

Both widths are kept in the browser rather than on the account, because they
belong to the window they were chosen in: the same person on a laptop and on a
wide monitor does not want one answer for both.

The middle pane searches title, creator, year and every field, sorts by title,
creator or date in either direction, and pages fifty at a time. The search is
the API's own, so it finds what the desktop client's quick search finds.

Everything that acts on that list — **Select**, **Export…**, emptying the trash,
the link to a public page — sits in one row at the end of its heading, next to
the search, because a control that acts on the list belongs beside the one that
narrows it. They are glyphs rather than words and each carries its name twice,
as `aria-label` for a screen reader and as `title` for a pointer; a control with
neither is a rebus. The search is one more glyph until it is pressed, and then
it unfolds into the field — a library is read far more often than it is
searched. It folds away again when it is left empty, never while it holds a
term: the term is the only thing on screen that says why the list is short.
Escape empties it, and a second Escape closes it.

The right pane shows an item's fields under the names the schema gives them,
its creators, tags and notes, and its attachments — which can be opened in the
browser or downloaded. A citation can be rendered there in Chicago, APA, MLA,
IEEE or Nature; the server renders it with the same CSL processor that answers
`format=bib`, rather than a second implementation in the browser.

### Collections

Collections can be made, renamed, moved and removed here.

**Where a collection goes is half of making one**, so it is settled before the
name is — and it is settled by which row you press. Every row that can hold
collections carries a plus, drawn when the pointer or the keyboard reaches it:
the row naming the library or the group makes one at its top level, since that
is the row the collections hang from, and a collection's makes one inside that
collection. Nothing depends on what happens to be selected, so there is no rule
to remember about where a new collection lands.

A dialog then opens, and it leads with where — the library, then every
collection down to the one this will sit in — before the field for the name.
That path is stated rather than offered as a choice: the sidebar lists one
library's collections under that library, so the row you pressed has already
said which library and which collection, and a picker here would be a second
way to say it that can disagree with the first. A new collection is selected
once it is made, and the branch it went into opens to show it, so it is where
you can see it rather than somewhere you have to go and find.

**Renaming, moving and removing are one dialog**, because they are one thought
— this collection's settings — and because a sidebar row has space for a pair
of icons rather than a menu of them. The pencil beside the plus opens it: the
name, the collection it sits inside, and Delete.

Moving is a picker rather than a drag. A tree can be taller than the window,
and a collection cannot be dropped on a parent that is scrolled out of sight;
items are dragged, a collection is moved by naming where it goes. The list
leads with the library, because "no parent" is not an absence to a reader — it
is the row the top-level collections hang from. What it never offers is the
collection itself or anything under it: a collection inside itself is a branch
that still exists and that nothing reaches, since the tree is drawn from
parents and neither end of the loop has one. The server refuses that write as
well, walking the whole way up from the proposed parent rather than checking
the one step `services/objectwrites.py` checks.

Delete asks in place rather than in the dialog, under the collection it is
about, where the tree can still be seen: it takes no answer beyond yes.

The controls appear only where the server says this account may write to the
library — a group that keeps editing to its administrators shows a member the
tree and nothing else.

**Removing a collection does not remove what is in it.** The items stay in the
library, the subcollections move up to where their parent was, and only the
collection itself goes. That is what the v3 `DELETE` does, so a collection
removed in the browser is a collection removed exactly as a syncing client
would have removed it, down to the entry in the deletion log that tells every
other client it went. Zotero also offers deleting a collection *with* its
items; that is a write to items, which the browser does not do.

There is no undo, because there is no trash around a collection here — the
question is asked before the collection goes instead. The desktop client's own
trash for collections is a client-side state that only it and the sync protocol
maintain.

Behind it is `services/objectwrites.py`, which is what the v3 endpoints write
through as well: the same key format, the same validation, and one new library
version per request, whichever door it came in by. A collection made or renamed
in the browser appears in the desktop client at the next sync, in the right
place in the tree.

Changing one is a patch: a property that is not sent keeps what is stored, so
a rename cannot silently move a collection to the top level. `parentCollection:
null` is how the dialog asks for the top level; the stored form of that is
`false`, which is the v3 shape and what comes back.

#### Sharing one

"Share a collection, not an entire library?" has been open on the Zotero forums
since 2008 and is the longest-running request in this space. The collection
settings dialog answers it, and answers it as a **page** rather than as sync.

As sync it is impossible. A Zotero client syncs a library; scoping below one
means either telling a client that a library holds less than it does — which
breaks `since` and every version comparison that depends on it — or patching
clients, which altero does not do. So no API key reaches any of this, no
library version moves when a link is made or revoked, and no syncing client
ever learns that a share exists.

As a page it is a link, at `/app/shared/<token>`, that shows the collection
read-only to whoever opens it. It is the second part of the interface that
answers with no cookie at all, after the profile pages, and for the same
reason: it identifies nobody, and what it can reach was fixed when the link was
made.

Three questions, and they are the whole of the form:

- **How much of the tree.** The branch, which is what the sidebar shows when
  you click a collection, or the one collection alone.
- **Whether the files go.** A reading list is not the same thing to hand out
  as the PDFs, which is the same separation the publishing wizard makes.
- **How long.** An expiry, or none. A link given to a seminar in March is not
  one to leave working in November.

The link itself is shown once, by the request that makes it. Nothing is stored
that it could be rebuilt from, so a link that is lost is replaced rather than
recovered — the rule the invitation links follow. Afterwards the dialog lists
what a collection carries, when each was made, when it was last opened, and
offers to revoke it; revoking is a delete, so there is nothing left to turn
back on.

Making a link takes **write** access to the library, not read: giving a
collection away is a decision about the library rather than a use of it, and a
member who may only read a group's items is not the person to make it.

The page never shows the trash, and a reader cannot widen what they were given
— the library and the collection come out of the token, and the one parameter
that narrows anything is resolved against the shared subtree. A link that was
revoked, one that has expired, one that never existed and one whose collection
has been thrown away all answer **404**: they are the same fact from the
reader's side, and telling them apart would turn the link into a way of asking
which tokens are real. Deleting a collection deletes its links with it.

`api/routes/webshares.py` and `services/shares.py` are where this lives.

### Items

An item can be filed, trashed, restored, deleted and copied to another library
— all of it by dragging rows of the item list somewhere, and all of it also
without a pointer. What cannot be done here yet is editing an item's fields.

**Several rows can be picked out and carried together.** `Ctrl`-click — `Cmd`
on a Mac — adds a row and takes one away, `Shift`-click takes everything
between, and `Ctrl`-A takes the whole page: the conventions of every list
anybody has used, and the desktop client's own. A drag that starts on a row
already picked out carries all of them; one that starts anywhere else carries
that row alone and leaves the selection where it was, because picking rows out
is what a click is for and a drag that quietly changed the selection would hand
back a different list than the reader had. What is under the pointer says which
it is: a title, or a count.

None of those exist on a touch screen, and none of them can be reached from a
keyboard either — pressing a button fires a click with no modifier on it, so a
row that is only a button can only ever be selected on its own. **Select** is
what answers both. It draws a checkbox on every row and one on the heading line
for the whole page, and a checkbox is a control a finger can hit and a keyboard
reaches with `Tab` and `Space`. While it is on, pressing anywhere on a row
toggles that row: in a mode whose whole purpose is picking rows out, a tap that
opened the detail pane instead would be the mode failing to mean anything. A
mouse is not made to use it — the modifiers work whether it is on or off.

**A selection is one request and one new library version**, whichever errand it
is. Twenty rows dragged onto a collection is one thing the reader did; twenty
requests would be twenty versions for it, twenty entries in a group's activity,
and — if the tenth were refused — a selection half moved with nothing on screen
to say which half. The server resolves every item before it writes any, so the
whole selection lands or none of it does. Deleting for good is the same: it
refuses the request outright if any one row is not in the trash, rather than
taking the ones that are.

The right-hand pane follows. One row picked out and it describes that item; more
than one and it holds the count and the same errands — move or copy, move to
trash, restore, delete, export — drawn with the same glyphs, since three rows
picked out do not make trashing them a different errand. It does not show five
items' fields side by side, and it does not offer to publish them: the wizard's
questions are about the work in front of it — which of its files go, what its
Rights field says — so a selection has no one set of answers to give it. The
**My Publications** row refuses a drop of several for the same reason, and being
a row that would refuse, it does not light up.

**Dragging onto a collection files it there and leaves it where it was**, which
is Zotero's own rule: a collection is not a folder, and an item can be in
several. Holding `Shift` while dropping moves it instead — out of the
collection being shown and into the one it was dropped on, in one request and
one library version. Dropping on the library's own row takes it out of the
collection currently shown without trashing it, and dropping on the trash
trashes it.

**A collection can be carried too**: onto another collection to sit inside it,
onto the library's row to come back to the top level, onto the trash to be
*asked* about deleting it — a collection carries subcollections, and a finger
that landed on the wrong row should not be able to remove one. A row that would
refuse a drop never lights up: a collection cannot go inside itself or anything
under it, and it cannot cross into another library, which would be a copy of
the collection and everything filed in it.

**Dragging onto another library copies it**, with its notes and attachments and
tags. The original stays: a move would be a deletion nobody asked for on the
far side of a drag that can be started by accident. The copy is a new item in
the library it lands in — its own key, its own version — and the collections it
was in do not come with it, because those collections are in the library it
came from. An attached file is not copied at all: files are stored under their
digest, so the copy names the same bytes.

**Everything a drag does, the keyboard does too.** `Delete` on a row trashes
it — the whole selection if that row is part of it, and that row alone if it is
not, which is the rule the drag follows. In the trash it asks first, because
that is the one thing here that cannot be undone, and it names the item while
there is one to name and counts them once there are several: five titles in a
sentence is not a sentence anybody reads. The detail pane carries the same
errands as controls of its own: “Move or copy…”, which opens one list holding
this library's collections and the other libraries it could be copied to,
“Move to trash”, and “Restore” and “Delete” for something already in the trash.
A control only a pointer can reach is a control some readers do not have.

They are glyphs, like the tools over the item list, and each carries its name
twice — as `aria-label`, which is what a screen reader announces, and as
`title`, which is what a pointer reveals. Two of them are drawn apart from their
neighbours on purpose: deleting for good is a bin with a cross through it rather
than the bin that means the trash, because it is the one act here that cannot be
undone — and emptying the trash, over the list, carries that same glyph in that
same red, since it is the same act on more of them. The other is publishing,
which draws a plus where unpublishing draws a minus: a control that toggles has
to show which way it is about to go.

“Move or copy…” takes a selection as readily as one row, and asks the same two
questions of it: where they go, and whether they come out of where they are.
Only how it names what it is about changes, since a count is not a title.

The `Delete` key works on a collection in the sidebar too, and asks the same
question the settings dialog's Delete asks.

**Deleting for good happens only out of the trash.** Trashing sets `deleted` on
the item, which is what the desktop client's own trash does and what makes it
reversible; only an item already in the trash can be removed outright, and the
server refuses the shortcut rather than trusting the browser to have asked
first, and refusing the whole request rather than the rows it objects to.
Emptying the trash is offered only while the trash is what is showing, asks
before it goes ahead, and is the one errand here that reaches items nobody
picked out — which is what the trash is: a list of things already thrown away.
Trashed collections are left where they are — the browser never trashes one, so
anything in there came from the desktop and is not shown here at all.

#### Writing items out

**Export…** writes items as a file for another program to read. The desktop
client has three gestures for this — Export Library…, Export Collection… and
Export Items… — and they are one errand with three ways of saying which items,
so the interface has one dialog reached from three places: the list's header,
which exports what the list is showing, and the detail and selection panes,
which export the rows picked out.

**Rows picked out are what it offers first.** A selection is a decision somebody
has just made, and an export that went on writing the whole library would be
answering a question nobody asked — so the dialog asks which items, with the
selection as the answer already given and the way back out to all of it beside
it. Where the list is narrower than the library — a collection, the trash, a
search, a tag — that view is offered as well, so the ladder reads: these rows,
this view, the whole library. With nothing picked out and nothing narrowing the
list there is only one answer, and the dialog states it rather than asking. The
detail pane's Export… does not ask either: it sits beside one item and means
that item.

What the list is showing is exactly what the file holds. The export takes the
same query the list took — the scope, the collection, the search, the tags — so
a collection narrowed by a search exports that, and not the library behind it;
“the whole library” drops all four rather than only the ones the screen happens
to show. It does not stop at the end of the loaded page: an export over a
library of nine thousand items writes nine thousand entries, which is what
“export the library” has to mean. A selection is named item by item instead,
and is the same selection every other errand acts on.

Seventeen formats, which is every one the server can write and every one
zotero.org serves: **BibTeX**, **BibLaTeX**, **CSL JSON**, **RIS**, **CSV**,
**MODS**, **TEI**, **EndNote XML**, **Zotero RDF**, **Bibliontology RDF**,
**Unqualified Dublin Core RDF**, **Refer/BibIX**, **RefWorks Tagged**,
**Bookmarks**, **COinS**, **Simple Evernote Export** and **Wikipedia citation
templates**. They are `altero/cite/formats/`, ports of the same Zotero
translators the desktop client runs, and the same code the v3 API's
`format=bibtex` and the citation in the detail pane go through. The order is the
client's, which sorts its translator list by label, and the chosen one is
remembered per device as the client remembers its last translator. There are no
other questions: the client's export dialog also offers to export the attached
files, to write notes as their own entries and to abbreviate journal titles, and
all three are things a translator is asked about child items and files that an
export over the API has neither of.

Notes, attachments and annotations are left out, and the gesture is not offered
where they are all there is. Most of the formats have no entry for them — the
client's own BibTeX and RIS translators skip them by name — and offering an
export that came back empty would be worse than not offering it. A CSL JSON file
is a JSON array, which is what pandoc and citeproc read and what the client's
CSL JSON translator writes; the `{"items": …}` wrapper the v3 API puts around
the same objects is an API envelope, not a file format.

Exporting is a **read**, which is why it is offered wherever a library can be
read at all, including a group that reserves editing for its administrators and
a note or attachment's own pane. It carries nothing that reader could not open
item by item — unlike an archive, which is an administrator's affair.

### By touch

Dragging is not the browser's own drag and drop, and could not be: that API is
a mouse API, and a touch never produces a `dragstart` at all. Carrying a row is
built on pointer events instead, one code path for both — at the cost of doing
what the browser used to do, which is deciding when a press has become a drag,
finding what is underneath, and drawing what is being carried.

The two gestures differ in one place, and they have to. A mouse starts carrying
as soon as it has moved a few pixels with the button down, because a mouse has
nothing else it could be doing. A finger that moves is usually scrolling, so a
touch starts carrying only after it has stayed put for a third of a second —
and moving before that cancels the carry and leaves the scroll alone. Once a
carry has begun the page stops scrolling under it, and starts scrolling *for*
it when the carry nears the top or bottom of the window, so a tree taller than
a phone can still be dropped into. The click a browser fires after the gesture
is swallowed, or every drag would also select the row it started from.

`Shift` to move rather than file has no equivalent on a touch screen, which is
one of the reasons the dialog exists: “Move or copy…” carries a “take it out
of” checkbox that says the same thing. `Ctrl` and `Shift` to pick out several
rows have no equivalent either, and **Select** is the answer to that one — a
checkbox on every row, which is a control a finger can hit. It is not only a
touch affordance: a keyboard cannot press a row with a modifier held down
either, so the same checkboxes are how somebody working without a pointer picks
out more than one row.

`Shift` means two things and they do not collide: held while *dropping* it
moves rather than files, and held while *clicking* it takes everything between.
One needs the pointer to have moved and the other needs it not to have, so a
gesture is only ever one of them.

Everything a fingertip has to hit is sized for one — the controls on a sidebar
row, the row itself, the buttons in a dialog and the two grips between the
panes all grow where the browser reports a coarse pointer. Nothing anywhere is
revealed by hovering alone, since a finger cannot hover: the controls that fade
in under a pointer are simply drawn.

### Tags

A tag can be renamed here. It is the one thing the browser does that reaches
items, and it reaches them the only way a tag can be changed at all: a tag has
no existence apart from the items carrying it, so renaming one rewrites every
one of them. Nothing here chooses *which* items, adds a tag or removes one —
that is editing items, which the browser does not do.

It is the pencil on the tag, beside its name in the panel, dimmed until the
pointer or the keyboard reaches it. A dialog opens holding the name the tag
has, selected: a rename is nearly always a correction to what is there — a
misspelling, a capital, a stray space — rather than a different word, and
starting from the old name saves retyping it. The dialog says what will happen,
in Zotero's own words, and counts the items it will happen to. There is no undo.

**Renaming onto a name already in use merges the two.** The items carrying
either one end up carrying the survivor, and the panel is left with one tag
where it showed two. That is what the desktop client does, and it is usually
the point: `whales` and `Whales` are two tags until somebody says they are not.

The merge takes in every tag of the new name, not only the one that looks like
the tag being renamed. A name can be two tags here — one added by hand and one
by a translator — and a rename that absorbed only one of them would leave the
panel listing the new name twice, with two chips that filter the list
identically. An automatic tag also becomes a manual one when it is renamed or
absorbed, which is again the client's own behaviour.

Behind it is `services/objectwrites.rename_tag`, the same call the v3
`PATCH <prefix>/tags/<name>` makes, so a tag renamed in the browser is renamed
exactly as a syncing client would have renamed it: one new library version, a
new version on every item that carried it, and the old name in the deletion log
for every other client to pick up. The controls appear only where the server
says this account may write to the library.
[compatibility.md](../compatibility.md#renaming-a-tag) has the endpoint and why
it is not upstream's.
