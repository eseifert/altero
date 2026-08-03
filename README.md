# altero

A Python implementation of the [Zotero data server](https://github.com/zotero/dataserver)
supporting the version 3 of the [Zotero Web API](https://www.zotero.org/support/dev/web_api/start).

Its purpose is to let a person or an institution run Zotero synchronisation on
infrastructure they control, using unmodified Zotero clients.
[docs/motivation.md](docs/motivation.md) sets out the reasoning and the goals,
and says which of them are intentions rather than properties of the current
code.

## Status

Implemented:

- Authentication by `Zotero-API-Key` header, bearer token or `key` parameter,
  with per-library and per-group permissions
- `/keys/<key>` and `/users/<userID>/groups`
- The schema endpoints (`/itemTypes`, `/itemFields`, `/itemTypeFields`,
  `/itemTypeCreatorTypes`, `/creatorFields`, `/items/new`, `/schema`)
- Reading items, collections, saved searches and tags, including `format=json`,
  `keys` and `versions`, pagination with the `Link` header, sorting, `since`,
  and `If-Modified-Since-Version`
- Tag listings scoped to a library, a collection, one item, the top level or
  the trash
- Writing items, collections and saved searches, and deleting tags, with the
  multi-object response, version preconditions and `Zotero-Write-Token`
- Recognising an object re-sent unchanged, so it keeps its version and the
  library's does not move
- `inPublications`, the My Publications flag, with the refusals upstream
  attaches to it
- Trashing collections and saved searches, which sync as a `deleted` flag on
  the object rather than as a deletion
- `relations` on both items and collections, including a predicate that names
  several objects
- `/users/<id>/publications/items`, readable without a key
- Rate limiting, off unless configured, answering `429` with `Retry-After`
- Items of every type, including notes, attachments and annotations, whose
  fields the published schema does not list
- Client-supplied `dateAdded` and `dateModified`, kept as sent
- `/deleted?since=`, so a client that has been away can tell a deletion from an
  object it has not fetched
- Library settings, and attachment full-text, including the batch upload the
  desktop client uses
- The attachment file protocol, storing files once per digest
- Provisioning from the command line, CORS, and API version negotiation

Not implemented yet: Atom, bibliography and citation rendering, the export
formats, group creation through the API (the command line does it),
`publications/settings` and `publications/deleted`, and rate limiting.

The web interface (see below) covers registration, sign-in with a password or
an email address, a one-time code from an authenticator app, account settings,
in-app notifications, group invitations, and reading a library. Passkeys, OIDC,
SAML and one-time codes by email are not built yet.

Two things the desktop client asks for are not part of the published data server
either: `GET /retractions/list`, which it polls to flag retracted papers, and
the streaming API it opens a WebSocket to. Neither appears anywhere in the
dataserver source. altero answers the first with `404` rather than an empty
list, which would assert that nothing in the library has been retracted; the
client logs both failures and syncs normally. The streaming API is documented,
so it can be implemented — but it is reached at a fixed `wss://stream.zotero.org`
unless a second preference is changed, which is why the setup below turns it off.

Writes to a library are serialized, so one request produces exactly one new
version however many objects it touches. See
[docs/schema.md](docs/schema.md#concurrency).

## The web interface

A Vue 3 single-page application, served at `/app/`. It signs in with a
username and password, optionally behind a one-time code from an authenticator
app, and shows the library. The Zotero desktop client is unaffected by any of
it: the v3 API remains API-key only, and a session cookie is refused there on
purpose.

The first account can be registered from the browser. Registration is open
only while the instance has no users at all, so a fresh container is reachable
without shell access and closes itself the moment that account exists. After
that, accounts are made with `altero user add` and given a password with
`altero user password <username>`.

Accounts that predate this interface keep working exactly as they did. They
have no password until one is set, which means they can sync but cannot sign
in to the browser.

The design follows Material 3 with a teal accent, and light and dark follow the
operating system unless the user picks one. Nothing is loaded from a third
party -- no web fonts, no CDN.

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

### Account settings

Display name, password, email address, an authenticator app, and the list of
signed-in browsers, each of which can be signed out on its own. Anything that
touches a credential asks for the current password again: a session cookie is
what somebody who borrowed an unlocked laptop already has.

Setting up an authenticator is two steps. The secret is stored but ignored
until a code from the app proves it works, so an interrupted setup cannot lock
the account.

### Notifications and invitations

An administrator of a group library can invite an email address to it. If that
address belongs to an account here, the invitation appears in that person's
notifications and can be accepted or declined in the interface; if it does not,
the emailed link carries a token and whoever registers with that address can
accept it afterwards.

Both channels are used deliberately. Mail may be unconfigured, unconfirmed,
filtered or simply lost, and an invitation that exists only in an inbox is one
that frequently never arrives.

### Still to come

Passkeys, single sign-on through OIDC and SAML, one-time codes by email, and
editing rather than only reading.

## Compatibility

The target is the Zotero desktop application, so where the published
documentation and the official [dataserver](https://github.com/zotero/dataserver)
disagree, the dataserver wins — including its inconsistencies. Each one is
recorded in [docs/compatibility.md](docs/compatibility.md), and the database
schema is compared against theirs in [docs/schema.md](docs/schema.md).

## Requirements

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)

## Getting started

```sh
uv sync
cp config.example.py config.py
uv run alembic upgrade head
uv run altero user add <username>
uv run altero key add <username> --name laptop
uv run altero
```

The server listens on `http://127.0.0.1:8000` by default. `key add` prints the
new key once and it cannot be shown again.

## Running it in a container

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
```

That is PostgreSQL, altero and a volume for attachments. Everything the
container needs lives in `docker/`; run the commands from the repository root,
or `export COMPOSE_FILE=docker/compose.yaml` once and drop the `-f`. Migrations
run on start, so an upgrade is `docker compose pull && docker compose up -d`
with nothing to remember; a failed migration exits the container rather than
serving against a schema it does not understand.

That covers altero's own schema, not PostgreSQL's. The database is pinned to
PostgreSQL 18, and moving a volume across a major version of PostgreSQL is a
dump and restore — the image refuses to start on a data directory written by an
older one, naming the version that wrote it, rather than adopting it. `pg_dump`
against the old container and `psql` into the new one is the whole of it;
`altero library export` moves a library between instances but not the users and
keys that own it.

The API is published on the loopback interface only — put a TLS terminator in
front of it rather than exposing it directly. `ALTERO_PUBLISH_PORT` moves it,
and `POSTGRES_PASSWORD` should be set to something other than its default before
anything real goes in.

`GET /health` is the readiness probe, and is what the container's own
`HEALTHCHECK` polls:

```json
{"status": "ok", "version": "0.1.0", "apiVersion": 3, "schemaVersion": 42,
 "revision": "c1b573deea88"}
```

`revision` is the migration the database is stamped with, which is the question
worth asking during an upgrade. It answers `503` with nothing but
`{"status": "error"}` when the database cannot be reached: the endpoint needs no
credentials, so it says nothing about why.

For PostgreSQL outside a container, install the driver with the `postgres`
extra: `uv sync --extra postgres`.

### Rate limiting

Off by default, because a personal instance has nothing to throttle and a limit
nobody asked for turns a working sync into a stuck one. To allow, say, 600
requests a minute per API key:

```sh
ALTERO_RATE_LIMIT=600 ALTERO_RATE_LIMIT_WINDOW=60 uv run altero
```

A caller over its allowance gets `429` with `Retry-After` in whole seconds,
which is what the client pauses on. Unauthenticated requests are counted per
address, and `/health` is never limited.

The count lives in the serving process, so behind several workers each keeps its
own and the real allowance is that many times the configured one. It is there to
stop a runaway client, not a determined one; that belongs in whatever terminates
TLS in front of altero.

## Administration

The Web API cannot create accounts or issue credentials, so that is done from
the command line:

```sh
uv run altero user add <username> [--display-name NAME] [--id N]
uv run altero user list
uv run altero key add <username> [--name LABEL] [--read-only] [--groups]
uv run altero key list
uv run altero key revoke <key>
uv run altero group add <name> --owner <username> [--public]
uv run altero group member <group-id> <username> [--role admin]
uv run altero library list
uv run altero library set-version <user|group> <id> <version>
uv run altero library export <user|group> <id> <archive.zip>
uv run altero library import <archive.zip> [--replace]
```

### Moving a library to another server

```sh
uv run altero library export user 1 library.zip
# on the other instance, where the account must already exist
uv run altero user add <username> --id 1
uv run altero library import library.zip
```

The archive is a ZIP of JSON documents plus the attachment bytes, one copy per
digest. It carries the library's version and every object's, along with the
client timestamps and the deletion log, because a client that synced with the
original remembers all of that: a restore that renumbered versions would look
successful and lock every one of those clients out. `manifest.json` says what
produced it and what it contains.

Accounts and API keys are not in it. An archive is a library, not a user, so the
owning user or group has to exist on the target first — which also means an
archive cannot leak a credential by being copied around. Restoring into a
library that already holds objects is refused rather than merged; `--replace`
discards what is there.

### After recreating the database

A library recreated from an empty database counts from zero again, while clients
that synced against the original still hold the version they last saw. The
desktop client refuses to move its stored version backwards, so it can neither
upload — every sync fails with `_libraryStorageVersion cannot decrease` and
retries forever — nor reset itself out of the state, since **Restore to Server**
fails the same way.

Raise the server past what the client remembers, then sync:

```sh
uv run altero library set-version user 1 100
```

The client's own number is in its database, if you want to be exact rather than
generous:

```sh
sqlite3 ~/Zotero/zotero.sqlite \
    'SELECT version, storageVersion FROM libraries WHERE libraryID=1'
```

A version can only be raised, because lowering one is how a working deployment
locks its clients out. Note that objects the client already considers synced are
not re-uploaded, so anything written before the database was recreated stays
missing; use **Restore to Server** afterwards to force a full upload.

## Using it from the Zotero desktop app

The client's API base URL is a hidden preference. In Zotero, open
**Settings → Advanced → Config Editor**, accept the warning, and set:

    extensions.zotero.api.url = http://localhost:8000/

The trailing slash matters. Set one more, in the same editor:

    extensions.zotero.streaming.enabled = false

`api.url` does not redirect the streaming API. The client resolves that
separately, falling back to a compiled-in `wss://stream.zotero.org`, and sends
your API key to it — a key that grants full access to your private library goes
to zotero.org, which rejects it as unknown and may log it. See
[docs/compatibility.md](docs/compatibility.md). Then restart Zotero and open
**Settings → Sync → Link Account**.

Zotero authenticates by opening a page in the browser and polling until it is
approved. That approval is still given on the server rather than in the browser
— the web interface signs a person in to their own library, and handing a
desktop client a full-access API key from that same session is a separate
decision that has not been made yet:

```sh
uv run altero login list
uv run altero login approve <token> <username>
```

The client picks the key up on its next poll — usually within a few seconds —
and syncing proceeds normally. `login approve` issues a key unless you point it
at an existing one with `--key`.

Point a test installation at altero, not one holding a library you care about:
altero is not finished, and a sync sends the client's data to it.

## Configuration

Copy `config.example.py` to `config.py` and edit it. Every setting can also be
supplied as an `ALTERO_`-prefixed environment variable, which takes precedence
over the file:

```sh
ALTERO_PORT=9000 ALTERO_DEBUG=true uv run altero
```

Set `ALTERO_CONFIG` to load a configuration module from another path.

## Development

```sh
uv sync
uv run pre-commit install  # once per checkout

uv run pytest              # run the test suite
uv run ruff format         # format
uv run ruff check --fix    # lint
uv run ty check            # type-check
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers the layering rule, how behaviour is
checked against the reference implementation, and what a change is expected to
come with.

## License

[GNU Affero General Public License v3](LICENSE) or later.
