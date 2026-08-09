# The web interface

A Vue 3 single-page application, served at `/app/`. It signs in with a username
and password, optionally behind a one-time code from an authenticator app, and
shows the library.

The Zotero desktop client is unaffected by any of it: the v3 API remains
API-key only, and a session cookie is refused there on purpose. That boundary
is enforced by `tests/test_web_routes.py`, in both directions.

## Building it

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

## Accounts

Registration in the browser opens for three cases, and for nothing else:

- **The first account.** Always, so a fresh container is reachable by its owner
  without shell access. It closes again the moment that account exists.
- **`ALTERO_OPEN_REGISTRATION`**, if the deployment sets it. Off by default: an
  instance is somebody's own server rather than a service, and an open form on
  one reachable from the internet is an invitation to strangers.
- **An address somebody invited.** Whoever holds an unanswered invitation to a
  group may make an account with the address it was sent to, and nobody else
  may. Without this the emailed link landed on a form that refused it, which
  made inviting a person who is not here yet unreachable on any instance that
  had not opened registration outright.

The sign-in page offers a register link only for the first two: an invitation
opens the door for one address, and advertising the instance as open would
promise a form that refuses almost everybody. The link in the invitation goes
straight to the form.

Every other account is made with `altero user add` and given a password with
`altero user password <username>` — see [administration.md](administration.md).

Accounts that predate this interface keep working exactly as they did. They
have no password until one is set, which means they can sync but cannot sign in
to the browser.

## Account settings

Five sections behind a side panel — profile, sign-in and security, language and
time zone, API keys, import and export — rather than one page of cards. It was
one page until the cards outgrew a screen, and reaching the time zone meant
scrolling past the authenticator and every key on the account.

The panel is the library's: the same rows, the same fill on the current one, so
the two screens read as one application. Which section is showing is in the
path (`/app/settings/keys`) rather than in component state, so a section can be
linked to and the back button walks them. The slugs are not translated; an
unknown one falls back to the first section rather than to an empty page.

Display name, password, email address, an authenticator app, and the list of
signed-in browsers, each of which can be signed out on its own. Anything that
touches a credential asks for the current password again: a session cookie is
what somebody who borrowed an unlocked laptop already has.

Setting up an authenticator is two steps. The secret is stored but ignored
until a code from the app proves it works, so an interrupted setup cannot lock
the account.

## API keys

Settings lists the keys on the account: what each may do, when it was made, and
when and from where it was last used. That last part is what makes the list
worth having — a key never used, or last seen from an address nobody
recognises, is one to remove.

Creating a key asks for the password, because it hands out a new credential.
Revoking one does not: the moment somebody reaches for that is the moment a key
has leaked, and a password prompt there is friction in the wrong place. A key
is shown in full exactly once, when it is created, and as four characters
afterwards.

Use is recorded at most once a minute per key, and immediately when the address
changes. It is a convenience for deciding what to revoke, not an audit log.
Behind a reverse proxy the address recorded is the proxy's until
`ALTERO_FORWARDED_ALLOW_IPS` names it; see [deployment.md](deployment.md).

## Language and time zone

The interface speaks English, German, French, Spanish, Portuguese and Japanese.
Both settings live on the account rather than in the browser, so signing in
from another machine gives you your own language rather than that machine's,
and both default to following the browser — which is a setting in itself, not
an unset value.

Dates and times are formatted from those two together. Choosing a language does
not move your date format to another country: with German chosen on a machine
set to `de-AT`, the words are German and the dates Austrian. Timestamps the
server records — when an item was added, when a key was last used — are stored
as UTC and shown in your zone, so an item added at 22:30 UTC is the third of
the month in Berlin and the fourth in Tokyo.

What an item type, a field or a creator type is called is not translated here
at all: those names come from the schema, which carries Zotero's own
translations in 48 locales, and they follow the account's language — the item
list's column headings included. Where the interface's own messages name
something Zotero also names, they use Zotero's word for it, so the two
applications read as one vocabulary.

A personal library is called **My Library** everywhere the interface names one
— the sidebar, the dialogs, and the export and restore lists in settings — from
one function in `web/src/librarylabel.ts`. It is one function because it was
briefly two: the sidebar took Zotero's word for it while Import and export went
on printing the account holder's own name, which is one library under two names
on two screens of one application. The exception is the library an *archive*
was made from, which is named as its manifest recorded it: that one may be on
another server and belong to somebody else.

Where a row names something Zotero also names, the words are Zotero's own,
taken from `chrome/locale/<lang>/zotero/zotero.properties` and `zotero.ftl` in
the client rather than translated again here: `pane.collections.library`,
`.groupLibraries`, `.publications`, `.duplicate`, `.unfiled` and `.trash` for
the sidebar, `recently-read` and `menu-restoreToLibrary` for the two the client
keeps in Fluent. So the German sidebar says *Eintragsdubletten* and *Einträge
ohne Sammlung*, which are not the phrases anybody would arrive at unprompted —
and are what the desktop client next to it says. The one gap is Japanese
*Recently Read*, which Zotero itself has not translated; altero uses
最近読んだ項目 rather than leaving English in a Japanese sidebar.

That vocabulary rule is also why "Restore to Library" has a message of its own:
"Restore" alone is what the settings page calls putting an archive back, and
one message for both had German offering to replay an item from a backup.

The translations beyond English are mine rather than a native speaker's, and
are worth reviewing before an institution relies on them. Adding a seventh
language is one file in `web/src/locales`, plus its tag in
`services/locales.py`; `tests/test_locales.py` and
`web/src/locales/locales.node.spec.ts` fail if those two ever disagree, or if a
catalogue drifts from the English one.

## Browsing a library

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
and [compatibility.md](compatibility.md#the-desktop-clients-three-extra-views)
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

The right pane shows an item's fields under the names the schema gives them,
its creators, tags and notes, and its attachments — which can be opened in the
browser or downloaded. A citation can be rendered there in Chicago, APA, MLA,
IEEE or Nature; the server renders it with the same CSL processor that answers
`format=bib`, rather than a second implementation in the browser.

## Collections

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

## Items

An item can be filed, trashed, restored, deleted and copied to another library
— all of it by dragging one row of the item list somewhere, and all of it also
without a pointer. What cannot be done here yet is editing an item's fields.

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
it; in the trash it asks first, because that is the one thing here that cannot
be undone. The detail pane carries the same errands as words — “Move or copy…”,
which opens one list holding this library's collections and the other libraries
it could be copied to, “Move to trash”, and “Restore” and “Delete” for
something already in the trash. A control only a pointer can reach is a control
some readers do not have.

The `Delete` key works on a collection in the sidebar too, and asks the same
question the settings dialog's Delete asks.

**Deleting for good happens only out of the trash.** Trashing sets `deleted` on
the item, which is what the desktop client's own trash does and what makes it
reversible; only an item already in the trash can be removed outright, and the
server refuses the shortcut rather than trusting the browser to have asked
first. Emptying the trash is offered only while the trash is what is showing, asks
before it goes ahead, and is the one place the interface deletes more than one
thing at once — which is also the one place where that is the errand. Trashed
collections are left where they are — the browser never trashes one, so
anything in there came from the desktop and is not shown here at all.

## My Publications

Dropping a work on the **My Publications** row publishes it, and is the one
drop that asks before it acts. It has to: publishing is not filing. The
questions are the desktop client's, in the client's own order, and so are the
rules they set — [compatibility.md](compatibility.md#publishing-from-the-browser)
lists each rule beside the line of `Zotero.Items.addToPublications` it comes
from.

**What goes along.** Files and notes are separate answers, and each is offered
only where the item has one. Link attachments always go, since a link is a URL
the item's own fields already carry; a *linked file* never does, because this
server does not hold its bytes and so could not publish them.

**Whether the work is yours.** Nothing advances until that is confirmed, and
the sentence changes when files are included: distributing somebody's PDF is a
larger claim than listing their paper.

**Under what licence.** Only when files are being published — there is nothing
else to license. Reserved rights, a Creative Commons licence, or the public
domain; Creative Commons then asks the two questions that decide which of the
six it is, defaulting to the most restrictive of each pair. The licence's name
goes into the item's **Rights** field, unless the field already says something
and “Keep the existing Rights field” is ticked — in which case there is nothing
left to ask and the wizard ends there. The name shown is the name that will be
stored, in English, and
[compatibility.md](compatibility.md#publishing-from-the-browser) says why it is
not translated.

The whole of it is one request and one library version, however many notes and
files go with the work: publishing a work and its files is one decision, and a
client syncing afterwards sees it as one.

**Changing the licence afterwards** is the Rights field, which the detail pane
can edit — the pencil beside it, or “Not stated — say what it is” where the
item says nothing yet. That is where the desktop client changes a licence too:
its wizard refuses to run a second time on the same item
(`collectionTree.jsx`: “Item … already exists in My Publications”), and Rights
is an ordinary field in its Info pane. The dialog offers the same eight
licences the wizard does, by code and by name, and free text for everything
else a Rights field says — “© 1974 the author” as readily as a licence.

It is the only field this interface writes, and it states the version it is
replacing: filing and trashing are add-and-remove errands the server works out
against what is stored, so a stale page cannot express a wrong one, but typing
over a licence that another client changed while the page sat open is a lost
write. A stale edit is refused rather than applied.

**Taking it out again** is `Delete` in the My Publications view, or a button in
the detail pane, and it asks first. The work leaves the published list with its
published notes and files — including any that have since been trashed, which
were still published until now — and stays in the library with everything it
holds. Its `Rights` field is left as it is: a licence already granted is not
withdrawn by hiding the page. Inside the My Publications view a single note or
attachment can also be shown or hidden on its own, which is what the desktop
client offers there and nowhere else.

A group has no My Publications and none of this appears in one: publishing is
something an account does with its own library, and the server refuses it for a
group item in any case.

## Profile pages

Publishing something has to publish it *somewhere*. The desktop client's wizard
says so in every language it ships — "Items you add to My Publications will be
shown on your profile page" — and that page is what `/app/u/<username>` is.

It is a list rather than the library's three panes, because somebody reading it
is reading a bibliography: each entry opens in place to show the abstract, where
the work appeared, the licence its files are under, and the files themselves.
Everything on it goes through the same services and the same serialiser as the
library view, so an item on a profile page is the item a syncing client
receives; only which items exist differs, and that is `inPublications` and
nothing else. Notes and files appear only if they were published with the work —
which the wizard asked once, and does not ask again.

The licence links to the licence. A **Rights** field holding one of the eight
the wizard offers is shown as a link to the deed; anything else is shown as the
text it is, because guessing a URL for "© 1974 the author" would be inventing a
permission. Files are served from the profile itself, under the same rules
upstream applies — its own permission check falls through to `canAccessObject`,
which passes a published item, "for My Publications files".

Each entry can also be cited, in the same six styles the library's detail pane
offers and through the same renderer on the server. A list of somebody's work is
where a reader is most likely to want a citation of it, and the alternative was
a second CSL implementation, in a second language, to disagree with the first.

**The address is `/app/u/<name>`**, not `/app/<name>`, which is where zotero.org
puts it. A bare path would collide with the interface's own routes, so an
account called `settings` or `library` would have no page at all and every route
added later would quietly claim a username. The name is matched without regard
to case, and upstream's slug is accepted too, so a link formed the way
zotero.org forms one still arrives.

### Who can see it

Upstream has no such question: zotero.org is a service, its profiles are public,
and the dataserver serves `/users/<id>/publications/items` to whoever asks. This
server is somebody's own, and "published" on it can reasonably mean something
narrower — so the account decides, in settings under **Profile**:

- **Anyone**, with no account here. Upstream's behaviour, and what every account
  starts as, so nothing changed for work already published.
- **People with an account here.** The middle answer, and the reason the setting
  exists: an instance shared by a research group is neither the open web nor a
  private drive.
- **Nobody.** The page is hidden. The items stay in My Publications and stay
  flagged, so turning it back on publishes exactly what was there before.

The choice governs the v3 endpoints as well, not only the browser: a page that
refused a stranger while `curl /users/1/publications/items` listed the same work
would be a decoration rather than a setting. In v3 terms, **users** means any key
this server issued and **nobody** means a key that could read the library anyway
— so the owner's own desktop client goes on syncing My Publications whatever the
page says. See
[compatibility.md](compatibility.md#who-may-read-my-publications).

A page that may not be read answers 404, exactly as an unclaimed name does.
Distinguishing them would turn the address into a way of asking which usernames
have accounts behind them; the page itself says the useful half — that some
profiles are shown only to people signed in — without the server disclosing
anything.

## By touch

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
of” checkbox that says the same thing.

Everything a fingertip has to hit is sized for one — the controls on a sidebar
row, the row itself, the buttons in a dialog and the two grips between the
panes all grow where the browser reports a coarse pointer. Nothing anywhere is
revealed by hovering alone, since a finger cannot hover: the controls that fade
in under a pointer are simply drawn.

## Tags

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
[compatibility.md](compatibility.md#renaming-a-tag) has the endpoint and why
it is not upstream's.

## Moving in from zotero.org

Settings offers to copy your personal library out of zotero.org and put it
here: items, collections, tags, saved searches, notes, the trash, the deletion
log and the attachment bytes, at **the versions your clients already know**.
It is not an export and re-import — nothing is renumbered, so the copy is the
library rather than a new library with the same contents in it.

**It takes an API key, not your zotero.org password.** zotero.org has no
password sign-in for other programs; its API accepts a key and nothing else.
So the screen asks you to make one at zotero.org → Settings → Security →
Applications, allow it to read your personal library, and paste it in. The key
is used for that one copy and is never stored, logged or written to the
database.

**It replaces rather than merges.** A library here with anything in it is
refused unless you tick the box, exactly as restoring an archive is: two
libraries sharing one set of keys is not something a client could make sense
of. There is no trash around what it discards.

**Your desktop client will want to reset itself afterwards**, and should be
allowed to. Zotero refuses to sync a library it last synced under a different
account number without erasing its local copy first — `checkUser` in the
client's own sync code — and unless your account here happens to have the same
number as your zotero.org one, that is what it sees. Everything it needs is on
the server by then, so it re-downloads rather than losing anything. An
administrator who wants to avoid even that can create the account with
`altero user add <name> --id <zotero.org user id>` before migrating.

It takes minutes, not moments — thousands of items at a hundred a request, one
download per attachment, at whatever pace zotero.org allows — so the page
starts the work and then reports on it: the stage, the count within it, and at
the end what came across. **The record of a running migration lives in the
server process**, so an instance behind several workers can start one on
one worker and be told "nothing running" by another, and a restart forgets
that a migration happened. What it *did* is in the library either way.

If zotero.org refuses part of the library, the copy goes on without it and
says which part at the end. Its `/tags?format=versions` currently answers 500
for every library, so the tags arrive with the library's version rather than
their own — which nothing you can see depends on. Items, collections and saved
searches are the exception: those *are* the library, and a copy missing them
would not be one, so a failure there stops the migration with nothing written.

What it cannot bring: group libraries (only the personal one), and files
zotero.org has no copy of — a linked file was never uploaded, and a stored one
is only there if the account had the storage. Those attachments arrive as
items without their bytes, and are counted and named at the end rather than
passed over quietly. The same is true of anything this server cannot store: an
item is left behind and named, rather than stopping the rest of the library
getting through.

The command line does the same thing, with the archive left on disk:

```sh
uv run altero migrate zotero <username>
```

[compatibility.md](compatibility.md#reading-a-library-out-of-zoteroorg) covers
what the API cannot serve and what altero does instead.

## Import and export

Settings offers the archive `altero library export` writes, and reads one back.
It is a backup or a move between servers, not an export for another
application: every object at the version clients remember, the deletion log,
and the attachment bytes. What an item list offers — BibTeX, RIS, CSL JSON — is
the other thing, and lives with the items.

Exporting is a link rather than a fetch, so the browser streams it to disk and
shows its own progress; an archive is as large as the library it came from.

Restoring is the one place the browser writes to a library, and it writes all of
it, so it is fenced three ways:

- **The session picks the target, not the file.** The library is the one chosen
  on the screen. An archive names a library in its manifest and that name is
  ignored here — an uploaded file naming `user/2` would otherwise be restored
  over user 2's library.
- **Who may.** A personal library is its owner's. For a group, an administrator
  may take a copy, and only the owner may restore over one: that ends the
  library as its members knew it, which is what deleting the group does and is
  held to the same person.
- **The password again, and an explicit replace.** A library that already holds
  anything is left alone rather than merged into, unless "replace what this
  library already holds" is ticked — and then the screen says, before the
  button is pressed, that everything in that library goes, files included.

Both ends are the same `services/transfer.py` the command line uses, so an
archive from either can be read by either.

One thing to know before restoring a *different* library's archive over your
own: the version counter comes from the archive, so it can move backwards, and
a client that synced past that point will not notice what changed underneath
it. `altero library set-version` is the way out; see
[administration.md](administration.md#after-recreating-the-database).

## Groups

A screen of its own, reached from the header. It lists the groups the account
belongs to with how many people and items are in each and what this account may
do there, and it creates one — which is open to anybody signed in, a group
being a library of your own rather than something to be granted.

Opening a group shows its members and, to an administrator, the settings that
decide what everybody may do: whether the group is private or public, who may
read the library, who may add and change items, and who may upload files. Those
last three are Zotero's own `libraryReading`, `libraryEditing` and
`fileEditing`, enforced by the server rather than merely recorded — see
[administration.md](administration.md#group-policy).

What a screen offers follows the role the *server* resolved and sends back with
the group. Deciding it in the browser would mean a second implementation of the
permission rules, drifting against the one that actually refuses the request,
and a control that will be refused is a promise the interface cannot keep. So a
plain member sees no policy controls and no delete button at all.

Three things need more than a click. Handing a group on and deleting one are
the owner's alone, and deleting asks first, because everything in the group
goes with it and there is no trash around a library. Leaving is nobody's
permission but your own: a member who had to ask would be in a group they
cannot get out of.

The same operations are available to an API key and to the command line;
`services/groups.py` is the one place that decides any of it, so a role means
the same thing whichever door set it.

## Notifications and invitations

An administrator of a group library can invite an email address to it. If that
address belongs to an account here, the invitation appears in that person's
notifications and can be accepted or declined in the interface; if it does not,
the emailed link carries a token and whoever registers with that address can
accept it afterwards.

Both channels are used deliberately. Mail may be unconfigured, unconfirmed,
filtered or simply lost, and an invitation that exists only in an inbox is one
that frequently never arrives.

The emailed link lands on a screen that reads the invitation **without a
session**: somebody with no account here has to be able to see what they were
asked to join before deciding to make one. Answering it still needs one, and
the server still checks the address it was sent to — holding the link is not
the same as being the person it was offered to. Signing in or registering from
that screen comes back to it, so the thing they came to answer is the next
thing they see.

### What has happened in a group

The group's panel opens with its recent activity: who changed what, and when.
Every member sees it. It was asked for as a way of keeping up with a shared
library, and restricting it to the people who run the group would make it a
supervision tool instead.

An entry is one write request — the same unit as a library version — and it
names what the request touched: "4 items added or changed", then the titles.
The first three are shown and the rest summarised, because a request may carry
fifty objects and fifty titles under one line would bury the log rather than
fill it in.

The names are **what things were called at the time**, stored with the entry
rather than looked up when it is read. An item renamed next week must not
rewrite what it was called last week, and a deleted item has nothing left to
look up at all — which is the entry most worth being able to read.

The wording matches the digest that arrives by mail, so one change reads the
same way whichever way somebody hears about it. A change nobody can be
attributed to reads "Somebody": a write can reach a group library with a key
that names no person, and that is still something that happened.

What an entry does not say is what *about* an object changed. Recording that a
title went from one string to another means storing both, for every field of
every write; that is a different feature with a very different cost, and it is
not built.

This is the read side of the record the notification digest already keeps, so
it costs no extra writing. Upstream has wanted the same thing since
[dataserver#89](https://github.com/zotero/dataserver/issues/89) in 2019 and
offers a group RSS feed instead, which shows neither what was modified nor what
was deleted.

Alongside it, an item in a group library carries who added it and who last
changed it. That part is upstream's own.

### Hearing about a group

The same panel carries four switches for what the group should tell you about:
items added or changed, items deleted, people joining or leaving, and
collections. All off until somebody turns one on, per group rather than per
account — being in five groups and caring about one is the ordinary case, and
one switch for all of them would make that a choice between silence and five
groups' worth of noise.

This is the one thing in the group panel a plain member can change. It is your
own subscription: there is no address to point somebody else's notifications
at, and an administrator deciding what the members are mailed about is not a
power anybody asked for.

What arrives is a digest rather than a running commentary, and what decides
when it arrives is in [email.md](email.md#group-notifications). The interface
shows the same thing in the notifications panel whether or not mail is
configured.

## Design

The design follows Material 3 with a teal accent, and light and dark follow the
operating system unless the user picks one.

It is set in IBM Plex Sans, with IBM Plex Sans JP behind it for Japanese, and
both are served by this application: nothing is loaded from a third party, no
CDN, no request that tells anyone else who is reading. The faces are split by
`unicode-range`, so a page fetches only the subsets its text needs — some 60 kB
for a European language, about 1 MB the first time somebody reads Japanese —
and the system stack shows the words while that happens. Fingerprinted assets
are cached for good, so the second visit fetches none of it.

## Not built yet

Passkeys, single sign-on through OIDC and SAML, one-time codes by email, and
editing an item's fields — with one exception, the Rights field, because a
licence set when a work was published has to be revisable by whoever set it.
Collections can be made, renamed, moved and removed, an item can be filed,
trashed, restored, deleted, copied to another library and published to My
Publications, a tag can be renamed, and a whole library can be restored from an
archive or copied in from zotero.org — but no item's title, creators or dates
can be changed here, no item can be created, and a tag cannot be deleted or put
on something. Moving in from zotero.org brings the personal library only; a group
has to be made here and its members invited.

Making an account for somebody else, resetting their password and revoking
their credentials are shell operations, as is an operator's view of the
instance.
[administration.md](administration.md) says what that covers and
[motivation.md](motivation.md) why it matters.
