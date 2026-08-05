# altero

[![CI](https://github.com/eseifert/altero/actions/workflows/ci.yml/badge.svg)](https://github.com/eseifert/altero/actions/workflows/ci.yml)

**Run Zotero synchronisation on infrastructure you control.**

altero is a Python implementation of the [Zotero data
server](https://github.com/zotero/dataserver), serving version 3 of the [Zotero
Web API](https://www.zotero.org/support/dev/web_api/start). Point an unmodified
Zotero desktop client at it and it syncs the way it syncs against zotero.org —
items, collections, tags, groups, notes, annotations, attachments and full-text
— with the data on a machine you run.

It is one server process, one database and one directory of attachments: no
caching tier, no search cluster, no queue workers, no object store to provision
before the first request. SQLite for one person, PostgreSQL where concurrency
matters. A backup is a database dump and a directory.

## Before you start

- **The Zotero desktop application is the only client.** iOS and Android
  compile the server address into the build, so a phone cannot be pointed
  anywhere else. [Why, and why that will not
  change.](docs/motivation.md#the-precondition-everything-else-rests-on)
- **altero is not finished.** Point a test installation at it, not one holding
  a library you care about — a sync sends the client's data to it.
- **Zotero does not support this.** The preference that redirects the client is
  hidden and undocumented, and self-hosting has been declined upstream since
  2012. Nothing here can prevent that preference disappearing in a release.

## Quick start

Python 3.14 or newer and [uv](https://docs.astral.sh/uv/); or Docker, further
down.

```sh
uv sync
cp config.example.py config.py
uv run alembic upgrade head
uv run altero user add <username>
uv run altero
```

The server listens on `http://127.0.0.1:8000`. Now point Zotero at it: open
**Settings → Advanced → Config Editor**, accept the warning, and set

    extensions.zotero.api.url = http://localhost:8000/
    extensions.zotero.streaming.url = ws://localhost:8000/stream

then restart Zotero and open **Settings → Sync → Link Account**. Zotero opens a
browser page and waits for the key to be approved. Approve it from the shell:

```sh
uv run altero login list                       # shows the pending token
uv run altero login approve <token> <username>
```

Syncing starts on the client's next poll. If the [web
interface](docs/web-interface.md) has been built — it is, in the container
image — that page is a sign-in form instead and approves the key itself, with
no shell involved. [docs/clients.md](docs/clients.md) explains each step,
including why the streaming address needs a preference of its own: `api.url`
does not redirect it, and a client left at its compiled-in default hands your
API key to zotero.org.

In a container instead, which is PostgreSQL, altero and a volume for
attachments:

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
```

Migrations run on start, so an upgrade is `docker compose pull && docker
compose up -d`. [docs/deployment.md](docs/deployment.md) covers configuration,
health checks, rate limiting, reverse proxies and upgrading PostgreSQL itself.

## What works

Reading and writing items, collections, saved searches and tags, with version
preconditions, write tokens and the multi-object response; every item type,
including the notes, attachments and annotations whose fields the published
schema does not list; the attachment file protocol and full-text upload;
groups, permissions and My Publications; Atom feeds; citations and
bibliographies in any published CSL style, and export as BibTeX, BibLaTeX or
RIS. The streaming API is served too, at `/stream`, so a client pointed at it
learns of a change the moment it happens instead of waiting for its next poll.

Not yet: the other export formats, and full-text *search* — uploaded text is
stored and served back but is not reachable from a query.
[docs/status.md](docs/status.md) is the endpoint-level list, and says what the
desktop client asks for that no data server documents.

## The web interface

A Vue 3 application at `/app/`, in six languages, covering registration,
sign-in with an optional authenticator code, account settings, API keys,
notifications, group invitations, and browsing a library — collections, tags,
search, an item's details, its attachments and a citation. It reads; it does
not write.

The v3 API stays API-key only and refuses a session cookie, so none of it
reaches the sync protocol — see
[docs/web-interface.md](docs/web-interface.md).

## Administration

Accounts, keys, groups and library transfer are command-line operations:

```sh
uv run altero user add <username>
uv run altero key add <username> --name laptop
uv run altero library export user 1 library.zip
uv run altero library import library.zip
```

[docs/administration.md](docs/administration.md) is the full list, and covers
moving a library between instances and recovering after the database has been
recreated — the case where clients lock themselves out.

## Documentation

- [motivation.md](docs/motivation.md) — why this exists, the goals, and which
  of them are intentions rather than properties of the current code
- [status.md](docs/status.md) — what the API serves and what it does not
- [clients.md](docs/clients.md) — connecting a Zotero client
- [deployment.md](docs/deployment.md) — running, configuring and upgrading it
- [administration.md](docs/administration.md) — accounts, keys, groups,
  libraries
- [web-interface.md](docs/web-interface.md) — the browser application
- [compatibility.md](docs/compatibility.md) — every deliberate divergence from,
  and copied quirk of, the reference implementation
- [schema.md](docs/schema.md) — the database schema against the dataserver's

The target is the Zotero desktop application, so where the published
documentation and the official dataserver disagree, the dataserver wins —
including its inconsistencies.

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
