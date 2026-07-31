# altero

A Python implementation of the [Zotero data server](https://github.com/zotero/dataserver)
supporting the version 3 of the [Zotero Web API](https://www.zotero.org/support/dev/web_api/start).

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
- Writing items, collections and saved searches, and deleting tags, with the
  multi-object response, version preconditions and `Zotero-Write-Token`
- `/deleted?since=`, so a client that has been away can tell a deletion from an
  object it has not fetched

Not implemented yet: Atom, bibliography and citation rendering, the export
formats, file upload and download, full-text content, and group library
management.

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
```

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
uv run pytest              # run the test suite
uv run pytest --cov        # ... with a coverage report
uv run ruff format         # format
uv run ruff check --fix    # lint
uv run ty check            # type-check
```

The concurrency tests need PostgreSQL, since SQLite serializes writers and so
cannot exhibit the races they cover. They are skipped unless a server is named:

```sh
docker run -d --name altero-pg -e POSTGRES_PASSWORD=altero \
    -e POSTGRES_USER=altero -e POSTGRES_DB=altero -p 55432:5432 postgres:17-alpine
ALTERO_TEST_POSTGRES_URL=postgresql+asyncpg://altero:altero@localhost:55432/altero \
    uv run pytest tests/test_concurrency.py
```

Database migrations are managed with Alembic:

```sh
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

## License

[GNU Affero General Public License v3](LICENSE) or later.
