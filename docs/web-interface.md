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

The translations beyond English are mine rather than a native speaker's, and
are worth reviewing before an institution relies on them. Adding a seventh
language is one file in `web/src/locales`, plus its tag in
`services/locales.py`; `tests/test_locales.py` and
`web/src/locales/locales.node.spec.ts` fail if those two ever disagree, or if a
catalogue drifts from the English one.

## Browsing a library

Three panes, as the desktop client has: what to show on the left, the items in
the middle, the selected item on the right.

The left holds every library the account can open — the personal one, which
carries the account's own name, and any group — and under the one being read,
everything it can be narrowed to as a single list: the library's top level, a
view that includes child notes and attachments, the trash, and then the
collections, nested and expandable. They are one list rather than a list and a
headed section beneath it, because they are one kind of thing, which is how the
desktop client has them too. Under that is the tag list; picking tags narrows
the middle pane, and picking several requires all of them.

The middle pane searches title, creator, year and every field, sorts by title,
creator or date in either direction, and pages fifty at a time. The search is
the API's own, so it finds what the desktop client's quick search finds.

The right pane shows an item's fields under the names the schema gives them,
its creators, tags and notes, and its attachments — which can be opened in the
browser or downloaded. A citation can be rendered there in Chicago, APA, MLA,
IEEE or Nature; the server renders it with the same CSL processor that answers
`format=bib`, rather than a second implementation in the browser.

## Collections

Collections can be made and removed here. Everything else in a library is still
read-only: no item, note, tag or saved search is edited in the browser.

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

Removing one is the cross on its row, beside the plus, and asks in place rather
than in a dialog: it takes no answer beyond yes.

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
version per request, whichever door it came in by. A collection made in the
browser appears in the desktop client at the next sync, in the right place in
the tree.

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
changed it — that part *is* upstream's, and altero had not served it until now.

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
editing a library beyond its collections and its tag names — collections can be
made and removed, a tag can be renamed, and a whole library can be restored from
an archive, but no item can be changed, a tag cannot be deleted or put on
something, and a collection cannot be renamed or moved to another parent.

Making an account for somebody else, resetting their password and revoking
their credentials are still shell operations, as is an operator's view of the
instance. Groups are no longer among them, and neither is taking a backup of a
library.
[administration.md](administration.md) says what that covers and
[motivation.md](motivation.md) why it matters.
