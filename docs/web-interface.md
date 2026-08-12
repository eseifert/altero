# The web interface

A Vue 3 single-page application, served at `/app/`. It signs in with a username
and password, optionally behind a one-time code — from an authenticator app or
sent by email — and shows the library.

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

Every other account is made by an instance administrator — under
**Administration → Accounts** in the browser, or with `altero user add` and
`altero user password <username>` from a shell. See
[administration.md](administration.md).

**A forgotten password** is offered on the sign-in page only where the
deployment set `ALTERO_PASSWORD_RESET` and configured a relay; otherwise an
administrator issues the link. The form says the same thing whatever it finds —
"if an account here uses that address, a link is on its way" — because a page
that said otherwise would answer, one address at a time, which addresses have
accounts here. It works only for an address that has been confirmed: nobody has
proved they hold an unconfirmed one, and honouring it would make a typo at
registration somebody else's way in.

**Signing in through somebody else's directory** is offered where an operator
has configured one — see [administration.md](administration.md#sign-in-providers).
The button appears above the password form, which stays: federation is an
addition, not a replacement, and an instance keeps its local accounts.

What a completed sign-in produces is a browser session, exactly the one a
password produces. **A Zotero client still holds an API key, and still gets it
from Settings → API keys.** That is the boundary rule doing its job rather than
a gap: the v3 API takes keys and nothing else, and no amount of single sign-on
changes it. It is the first question an institution asks, so it is answered
here rather than in a footnote.

An account here is matched to a directory by its **subject** — the opaque
identifier the directory issues — and never by an email address. A directory
that can assert an address would otherwise be able to take the account holding
it, which is the usual way federated sign-in is broken into. So a first sign-in
that nobody has connected either makes a new account, where the operator allows
that, or is refused; it never adopts one. Connecting a directory to an account
you already have is done from **Settings → Sign-in and security**, while signed
in, exactly as enrolling an authenticator is.

Accounts that predate this interface keep working exactly as they did. They
have no password until one is set, which means they can sync but cannot sign in
to the browser.

## Account settings

Five sections behind a side panel — profile, sign-in and security, language and
time zone, API keys, import and export — rather than one page of cards, which
at this many cards means scrolling past the authenticator and every key on the
account to reach the time zone.

The panel is the library's: the same rows, the same fill on the current one, so
the two screens read as one application. Which section is showing is in the
path (`/app/settings/keys`) rather than in component state, so a section can be
linked to and the back button walks them. The slugs are not translated; an
unknown one falls back to the first section rather than to an empty page.

Display name, password, email address, an authenticator app, and the list of
signed-in browsers, each of which can be signed out on its own. Anything that
touches a credential asks you to prove again that the browser is yours: a
session cookie is what somebody who borrowed an unlocked laptop already has.
The usual proof is the current password, and once it has been given it stands
for five minutes, so changing a password and then making a key is one prompt
rather than two. An account that has no password — one an administrator created
and never set one for — proves itself the other ways it can, and is not shut
out of its own settings for lacking a credential it was never given.

Setting up an authenticator is two steps. The secret is stored but ignored
until a code from the app proves it works, so an interrupted setup cannot lock
the account.

**A passkey signs you in on its own.** Your device checks it is you — a
fingerprint, a face, a PIN — and there is no password to steal, phish or
reuse. It is the strongest way in this interface has, and the sign-in page
offers it before the password form.

That is why it is not followed by a second factor: the authenticator has
already established both that somebody is present and that it is you, and
asking for a code afterwards would add something weaker than what was just
presented. A passkey also counts as having proved yourself, so the things that
would otherwise ask for your password again — making an API key, changing your
address — do not ask twice.

**No username is typed.** The browser offers whichever passkey it holds for
this site, and the assertion says whose it is. There is no form here that
behaves differently for a name that exists, so the sign-in page cannot be used
to ask who has an account.

Adding one asks for your password, because a passkey is a way *in* rather than
a hurdle in front of one — the same rule an API key follows. Removing one asks
too, and the last way in cannot be removed: an account with no password and one
passkey would otherwise be able to lock itself out of a library nobody else can
reach. Where a passkey lives on a single device rather than being backed up,
the list says so, which is worth knowing when it is your only one.

Passkeys need `ALTERO_PUBLIC_URL` and are not offered without it. A passkey is
bound to the address it was enrolled at, and an instance that guessed that from
whatever request arrived would make passkeys that stop working the day the
address changes — silently, weeks later. The sign-in page asks the server
rather than assuming.

**A code by email** is the second factor for anyone with no authenticator app,
and the way back in for anyone who had one and lost the phone. It needs a
confirmed address and nothing else — there is no secret whose working has to be
proved, only an address somebody proved they could read — so turning it on is
one step rather than two. It is a weaker factor than an app, and where both are
enrolled the app is asked for; **Use a code by email instead** is on the
sign-in screen, which is what makes it a recovery path rather than a
convenience. Before it existed, an account with an unreachable authenticator
had exactly one way back: find whoever runs the server.

The code lasts ten minutes, works once, and works only in the browser that
asked for it — so somebody who reads the message cannot use it from their own
machine. Five wrong guesses throw it away rather than leaving six digits
standing to be walked through, and asking for another stops the one before it
working.

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

The interface speaks English, German, French, Spanish, Portuguese, Italian,
Dutch, Danish, Polish, Russian, Japanese and Chinese.
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

No date rule is written down anywhere in altero, and adding a language does not
add one. `web/src/formats.ts` hands the formatting tag and the zone to `Intl`
and takes what the CLDR data in the browser gives back, so Danish separates the
hour with a full stop — *4. apr. 2019, 00.30* — Russian ends a date in *г.*,
Chinese and Japanese write 2019年4月4日, and none of that is altero's doing.
Sizes go the same way, which is why a Russian reader is told *1,5 МБ* although
no catalogue holds a byte unit. What the tests in `stores/locale.spec.ts` hold
is the one thing that *is* ours: that each language reaches `Intl` at all, a
wrong tag being the failure that would otherwise show every reader English
dates in a translated page.

The one language whose tag is coarser than its readers is Chinese. There is a
single catalogue and it is Simplified, so `zh-TW` narrows to it and somebody in
Taipei gets Simplified words — with Taiwanese dates, by the rule above. The
picker says 简体中文 rather than 中文 so that this is visible before it is
chosen.

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
and are what the desktop client next to it says. The gaps are the rows Zotero
itself has not translated: *Recently Read* in Japanese, Danish and Dutch, and
*Items* in Danish. Leaving English standing in those sidebars would be worse
than translating them here, so altero does — 最近読んだ項目, *Læst for nylig*,
*Onlangs gelezen*, *Elementer* — following the word the rest of that locale
already uses.

That vocabulary rule is also why "Restore to Library" has a message of its own:
"Restore" alone is what the settings page calls putting an archive back, and
one message for both had German offering to replay an item from a backup.

Counting is not the same everywhere, and a message with a number in it says so.
English separates one from many, and German, French, Spanish, Portuguese,
Italian, Dutch and Danish separate it the same way; Japanese and Chinese inflect
nothing and write the one form twice, so the branch that gets picked does not
matter. Polish and Russian have a third form for the small counts — *2 elementy*
against *5 elementów*, *2 записи* against *5 записей* — so their catalogues
carry three branches and `pluralRules` in `web/src/i18n.ts` chooses between
them. A catalogue written with English's two would be wrong on every count from
2 to 4, so `locales.node.spec.ts` holds each catalogue to the number of forms
its own language has rather than to English's — a check against English would
have called "2 elementów" correct.

The translations beyond English are mine rather than a native speaker's, and
are worth reviewing before an institution relies on them. Adding another
language is one file in `web/src/locales`, plus its tag in
`services/locales.py` and in `MESSAGES` in `web/src/i18n.ts` — and a plural
rule beside it if the language needs more than two forms.
`tests/test_locales.py` and `web/src/locales/locales.node.spec.ts` fail if the
server's list and the catalogues ever disagree, or if a catalogue drifts from
the English one.

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

### Sharing one

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

## Items

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

### Writing items out

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

Four formats, because they are the four the server can write: **BibTeX**,
**BibLaTeX**, **RIS** and **CSL JSON**. The desktop client offers a dozen more
through JavaScript translators run by a translation server, which altero has no
equivalent of; these four are `altero/cite/`, the same code the v3 API's
`format=bibtex` and the citation in the detail pane go through. The chosen one
is remembered per device, as the client remembers its last translator. There
are no other questions: the client's export dialog also offers to export the
attached files, to write notes as their own entries and to abbreviate journal
titles, and all three are things a translator does that none of these four can.

Notes, attachments and annotations are left out, and the gesture is not offered
where they are all there is. None of them has a bibliography entry, and altero
has no note translator to write one with — the client's own BibTeX and RIS
translators skip them too. A CSL JSON file is a JSON array, which is what
pandoc and citeproc read and what the client's CSL JSON translator writes; the
`{"items": …}` wrapper the v3 API puts around the same objects is an API
envelope, not a file format.

Exporting is a **read**, which is why it is offered wherever a library can be
read at all, including a group that reserves editing for its administrators and
a note or attachment's own pane. It carries nothing that reader could not open
item by item — unlike an archive, which is an administrator's affair.

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
and the attachment bytes. The other thing — BibTeX, BibLaTeX, RIS and CSL JSON
— lives with the items, under
[Writing items out](#writing-items-out).

Both are a link rather than a fetch, so the browser streams the file to disk and
shows its own progress; an archive is as large as the library it came from, and
a library's worth of BibTeX is not something to assemble in memory either.

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

## Administration

A screen of its own, reached from an icon the header draws only for an account
that administers the instance — usually nobody at all on a personal server, and
one person on a departmental one. Every route behind it is refused to anybody
else, so the icon hides a door rather than guarding one; see
[administration.md](administration.md#who-administers-the-instance) for who has
the role and how it is handed on.

It is the one part of this interface that is about the instance rather than
about a library. **Overview** says what the server is running and how much of
everything it holds; **Storage** says what each library costs on disk, against
what the instance actually holds; **Accounts** makes an account for somebody
else, resets a password, suspends an account and deletes one; and **Retention**
says how long this server keeps what nobody asked it to keep. Each of those
writes asks for your own password, as the account's own screens do.

What none of it does is read. No screen here answers with an item, a title, a
note or a file, and administering the instance adds nothing to what its holder
may see in anybody's library. Deleting an account is the one operation that
reaches into a library, and it reads nothing on its way through. The two that
remove anything — that, and deleting files no library references any more — ask
for your own password, as the account's own screens do.

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

Beside those, each member carries a permission of their own: whatever the group
allows, read only, only their own items, or add but not remove. Zotero has no
such notion — its groups decide who may edit once, for everybody — and these
are the three finer roles the forums have asked for since 2010. A permission is
a ceiling under the group's policy rather than a way past it, an administrator
cannot be given one, and an invitation can carry one so that being asked to
read a library and being asked to work on it are different invitations.
[compatibility.md](compatibility.md#finer-roles-for-one-member) has the table
and the two decisions behind it — how a read-only member is expressed to a sync
client, and why the other two show up as sync errors when a desktop client
tries anyway. The item list here knows about all of them and does not draw a
control the server would refuse.

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
operating system unless the user picks one. What altero does inside that frame
is written down in [design.md](design.md): one rule — fill groups, outline
controls, hairline separates — three surface steps, one card recipe that every
screen imports rather than draws itself, and a toolbar around every row of
icon-only tools, because a glyph on a page says nothing about being pressable
until a pointer rests on it. `styles/surfaces.node.spec.ts` fails when a
component draws a surface of its own.

The target is WCAG 2.2 AA. What can be measured is measured in tests that fail
— every contrast pair the interface puts on screen, and the ordering that keeps
a hovered row from looking more chosen than a chosen one — and
[design.md](design.md#accessibility) says which criteria were decided where,
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

## Not built yet

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
above. [administration.md](administration.md) says what the shell covers alone
and what it shares with the browser.
