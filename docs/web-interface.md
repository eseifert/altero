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

The left holds every library the account can open — the personal one and any
group — with the collection tree beneath, nested and expandable, plus the trash
and a view that includes child notes and attachments. Under that is the tag
list; picking tags narrows the middle pane, and picking several requires all of
them.

The middle pane searches title, creator, year and every field, sorts by title,
creator or date in either direction, and pages fifty at a time. The search is
the API's own, so it finds what the desktop client's quick search finds.

The right pane shows an item's fields under the names the schema gives them,
its creators, tags and notes, and its attachments — which can be opened in the
browser or downloaded. A citation can be rendered there in Chicago, APA, MLA,
IEEE or Nature; the server renders it with the same CSL processor that answers
`format=bib`, rather than a second implementation in the browser.

Reading only, for now. Nothing in the interface writes to a library, which is
also why no request from it can lose a sync conflict.

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
editing a library rather than only reading it.

Making an account for somebody else, resetting their password and revoking
their credentials are still shell operations, as is an operator's view of the
instance. Groups are no longer among them.
[administration.md](administration.md) says what that covers and
[motivation.md](motivation.md) why it matters.
