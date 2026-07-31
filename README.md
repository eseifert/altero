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

Not implemented yet: writes (`POST`/`PUT`/`PATCH`/`DELETE`), `/deleted`, Atom,
bibliography and citation rendering, the export formats, file upload and
download, and group library management.

## Requirements

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)

## Getting started

```sh
uv sync
cp config.example.py config.py
uv run alembic upgrade head
uv run altero
```

The server listens on `http://127.0.0.1:8000` by default.

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

Database migrations are managed with Alembic:

```sh
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

## License

[GNU Affero General Public License v3](LICENSE) or later.
