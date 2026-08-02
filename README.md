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
`/publications`, and rate limiting.

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
```

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

The trailing slash matters. Then restart Zotero and open
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
