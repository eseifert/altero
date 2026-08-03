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
docker compose up -d
docker compose exec altero altero user add <username>
```

That is PostgreSQL, altero and a volume for attachments. Migrations run on
start, so an upgrade is `docker compose pull && docker compose up -d` with
nothing to remember; a failed migration exits the container rather than serving
against a schema it does not understand.

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
approved. altero has no web interface and stores no passwords, so the page it
serves tells you to approve the login on the server instead:

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
