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

The first account can be registered from the browser. Registration is open only
while the instance has no users at all, so a fresh container is reachable
without shell access and closes itself the moment that account exists. After
that, accounts are made with `altero user add` and given a password with
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

## Notifications and invitations

An administrator of a group library can invite an email address to it. If that
address belongs to an account here, the invitation appears in that person's
notifications and can be accepted or declined in the interface; if it does not,
the emailed link carries a token and whoever registers with that address can
accept it afterwards.

Both channels are used deliberately. Mail may be unconfigured, unconfirmed,
filtered or simply lost, and an invitation that exists only in an inbox is one
that frequently never arrives.

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
editing rather than only reading.

Administering anybody other than yourself is still a shell operation, as is an
operator's view of the instance. [administration.md](administration.md) says
what that covers and [motivation.md](motivation.md) why it matters.
