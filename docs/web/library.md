# Browsing and organizing a library

The browser interface is a companion to Zotero Desktop. It lets you browse, search and organize a library and edit an item's fields, but it is not intended to replace the desktop application.

## Common tasks

- Browse collections, tags and search results from the library view.
- Create, rename, move and remove collections.
- Make an item, edit its fields, creators and tags, change its type, and relate it to others.
- Write notes, on their own or under an item.
- Add files and web links, on their own or under an item, and rename or replace a file.
- File, trash, restore, delete or copy items.
- Rename tags across a library.
- Use the same actions with mouse, keyboard or touch where the interface provides them; `?` lists the keys.

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
browser or downloaded. An attached web page or SVG opens with its scripts
switched off, and a note shows without any image it links from elsewhere. A citation can be rendered there in Chicago, APA, MLA,
IEEE or Nature; the server renders it with the same CSL processor that answers
`format=bib`, rather than a second implementation in the browser.

Item headings use Zotero's title field for each type: **Case Name** for cases,
**Subject** for emails and **Name of Act** for statutes. The same titles appear
on public profiles and shared collection pages. An empty case name, subject or
act name shows “(untitled)”.

### Editing an item

Where you may change the library, the right pane shows every field of the
item's type, empty ones included, in the order Zotero Desktop shows them.

- **Make an item** with **+** over the item list, then choose its type. The
  five types you used last come first, as in Zotero Desktop, then every type.
  The item opens with its title ready to type, and is filed into the
  collection being shown. **+** is not offered in the trash or My Publications.

- **Edit a field** by pressing its value; a frame under the pointer shows
  which values can be edited. Enter or leaving the field saves it, and Escape
  puts it back. Abstract and Extra take several lines: there, Shift+Enter
  saves. A URL or DOI is edited the same way and opened with the button
  beside it. Date Added and Date Modified are set by the server and shown
  dimmed.
- **Check a date.** Beside it, `y m d` shows how Zotero reads what you typed —
  `d m y` for `26.10.2026` in Germany, `m d y` in the United States.
- **Change the type** from the menu at the top. If the new type has no place
  for some fields, the pane lists them and changes nothing until you confirm.
  Fields move to their counterpart where there is one: a book's publisher
  becomes a report's institution, and a book's author a film's director.
- **Edit creators** below the title. Each has a role, chosen from those the
  item type allows, and a last and first name — or one full name, for an
  institution, switched under **More Options…**. **+** adds a creator after
  the row in the same role, **−** removes one, and a creator whose names are
  emptied is removed when you leave it. Drag the grip beside the role to
  reorder, or use **Move Up** and **Move Down** under **More Options…**.
- **Rights** is set with the license chooser, as for My Publications.
- **Tag an item** under **Tags**: **+** opens a box that offers the library's
  tags as you type. Enter adds the tag and leaves the box open for the next;
  several lines pasted at once add one tag each. Press a tag to rename it on
  this item, or clear it to remove it; **×** removes it too. Tags coloured in
  Zotero Desktop come first, with their colour, then tags with an emoji, then
  the rest alphabetically. A dashed outline marks a tag added automatically,
  by a translator or an import.
- **Relate items** under **Related**: **+** searches the library, and pressing
  a result relates the two. Both items name each other, as in Zotero Desktop,
  and **−** removes the link from both. Pressing a related item opens it.
  Related items in the trash are listed only while the item itself is there.

Each save is one change, which Zotero Desktop receives on its next sync.
Changes arrive the other way too: while the page is open, a change made
elsewhere — Zotero Desktop syncing, someone else in a group — shows up in the
list and the open item within a moment, without a reload. A field you are
typing in is left as you have it. This needs a single server process; see
[Behind a reverse proxy](../deployment.md#behind-a-reverse-proxy).

If someone else changed the item while you were editing it, the pane shows
the item as it is now. Your edit is saved anyway when they changed something else. When
they changed the same field, or the creators, nothing is written: the pane
shows the local version (yours) and the remote version (theirs), and **Choose
this version** keeps one. Tags are always saved — your addition, removal or
rename is made on top of theirs.

An item in the trash cannot be edited, as in Zotero Desktop: restore it first.
A group member who may only read sees the fields without editing controls.

### Writing a note

A note opens in an editor in the right pane, and is saved a second after you
stop typing, as in Zotero Desktop; **Saved.** above the note says so. A note
left before then — another item opened, the tab closed — is saved on the way out.

- **Make a note** with the note button over the item list: **New Standalone
  Note** files it into the collection being shown, **New Item Note** puts it
  under the item picked out. **+** beside **Notes** in an item's pane adds one
  under that item. The note opens ready to type.
- **Format text** by selecting it: a bar appears over the selection with the
  block type (paragraph, headings, monospaced, lists, block quote), bold,
  italic, underline, strikethrough, code, link, text and highlight colour, and
  under **More** alignment, indent, subscript, superscript and clear
  formatting. On a phone or tablet the same tools sit on the keyboard while you
  write instead, with undo and redo.
- **Type `/`** at the start of a line or after a space for a list of block
  types; keep typing to narrow it (`/h2`, `/quote`, `/ul`), and press Enter.
  Zotero Desktop's keys work too — Ctrl+B, Ctrl+K for a link, Tab to indent or
  move a list item in, Shift+Ctrl+1 to 6 for headings — and so does Markdown
  typed at the start of a line: `#`, `-`, `1.`, `>`, ```` ``` ````, `---`.
- **Links** are edited in the bar over them, which also opens the link under
  the cursor in a new tab.
- **Write full screen** with the button above the note: the note fills the
  window until you press it again or Escape.
- **Leave the text** with Escape or Alt+F10, which move to the tools; Escape
  there comes back. Tab inside a note indents, as on the desktop.

A note is saved as Zotero Desktop's note editor would write it, so a note
edited here and opened there reads the same. Opening a note writes nothing:
only a change you make is saved. Citations, annotations and embedded images
made in Zotero Desktop are shown and kept, but cannot be added here, and maths
shows as its TeX source. A note written by a newer version of Zotero than this
interface knows is shown read-only, as older versions of Zotero Desktop do.

If the note changed elsewhere while you were typing, nothing is written: the
pane names the local version and the remote version by their first lines, and
**Choose this version** keeps one. A note changed elsewhere while you are only
reading it shows the change straight away.

### Adding files and links

A file added here is stored on this server and synced to Zotero Desktop like a
file the desktop added: the desktop downloads it, under the name it had.

- **Add a file under an item** with **Attach File…**, from the paperclip over
  the item list or from **+** beside **Attachments** in the item's pane, or drag
  files from your computer onto the item's row or its pane.
- **Add a file on its own** with **Add File…**, which files it into the
  collection being shown, or drag files onto a collection, the library or the
  list itself.
- **Attach a web link** with **Attach Web Link…**: an address and, if you want
  one, a title. Without a title the link is named after its address, as in
  Zotero Desktop. An address typed without `https://` gets `http://`.
- **Rename a file** by pressing its **Filename** in the attachment's pane, as
  in Zotero Desktop: a name typed without an extension keeps the old one, and
  a different extension is asked about first. The title stays as it was, and
  nothing is uploaded again; Zotero Desktop renames its own copy when it syncs.
  An attachment's title is edited the same way.
- **Replace a file** with **Replace File…** in an attachment's pane. The
  attachment keeps its title and takes the new file's name.

Files go up one at a time, each with a progress bar in the corner of the window
and a button to cancel it. A file that could not be added stays there, saying
why, until you dismiss it. Folders cannot be dropped; add the files inside
them.

The first PDF, ebook, web page, image, audio or video file under an item is
titled after its kind ("PDF"), and any other after its file name, as in Zotero
Desktop. Zotero Desktop's automatic renaming of files from the item's metadata
is not done here.

Files cannot be added to a group whose
[file editing setting](../administration.md#group-policy) keeps them to administrators or
allows none; web links can. The largest file accepted is set by
[`ALTERO_MAX_UPLOAD_MB`](../configuration.md#server-and-storage), 1 GiB by
default. If somebody replaced the same file elsewhere while yours was going up,
yours is refused rather than written over theirs, and the pane shows theirs.

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
without a pointer. Its fields, creators and type are edited in the right pane; see
[Editing an item](#editing-an-item).

**Several rows can be picked out and carried together.** `Ctrl`-click — `Cmd`
on a Mac — adds a row and takes one away, `Shift`-click takes everything
between, and `Ctrl`-A takes the whole page: the conventions of every list
anybody has used, and the desktop client's own. A drag that starts on a row
already picked out carries all of them; one that starts anywhere else carries
that row alone and leaves the selection where it was, because picking rows out
is what a click is for and a drag that quietly changed the selection would hand
back a different list than the reader had. What is under the pointer says which
it is: a title, or a count.

**The keyboard moves through the list** as in Zotero Desktop's item tree. The
list is one stop for `Tab`; `↑` and `↓`, `Home` and `End`, and `Page Up` and
`Page Down` (ten rows) move the selection, and the right pane follows. `Shift`
with an arrow extends the selection, and `Ctrl` (`Cmd`) with an arrow moves
without selecting, so that `Ctrl`+`Space` can add the row reached or take it
out. Moving past the last row shown reads the next page. `Enter` moves into the
item's pane, and `F2` opens its title for typing. `?` lists all of this.

None of the modifiers exist on a touch screen. **Select** answers that. It
draws a checkbox on every row and one on the heading line for the whole page,
and a checkbox is a control a finger can hit. While it is on, pressing anywhere
on a row toggles that row, and the arrow keys move without selecting: in a mode
whose whole purpose is picking rows out, a tap that opened the detail pane
instead would be the mode failing to mean anything. A mouse is not made to use
it — the modifiers work whether it is on or off.

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
checkbox on every row, which is a control a finger can hit.

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

A tag can be renamed here, throughout the library: a tag has no existence
apart from the items carrying it, so renaming one rewrites every one of them.
To add or remove a tag on one item, or rename it there alone, use the item's
**Tags** section; see [Editing an item](#editing-an-item).

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
absorbed, which is again the client's own behavior.

Behind it is `services/objectwrites.rename_tag`, the same call the v3
`PATCH <prefix>/tags/<name>` makes, so a tag renamed in the browser is renamed
exactly as a syncing client would have renamed it: one new library version, a
new version on every item that carried it, and the old name in the deletion log
for every other client to pick up. The controls appear only where the server
says this account may write to the library.
[compatibility.md](../compatibility.md#renaming-a-tag) has the endpoint and why
it is not upstream's.
