# altero

[![CI](https://github.com/eseifert/altero/actions/workflows/ci.yml/badge.svg)](https://github.com/eseifert/altero/actions/workflows/ci.yml)

**Run Zotero synchronisation on infrastructure you control.**

altero is a self-hosted stand-in for the
[server](https://github.com/zotero/dataserver) behind zotero.org's syncing,
written in Python and speaking the same [web
API](https://www.zotero.org/support/dev/web_api/start) the Zotero client does.
Point an unmodified Zotero desktop application at it and it syncs the way it
always has — items, collections, tags, groups, notes, annotations, attachments
and full text — with your library on a machine you run.

It is meant to be small to look after:

- One server process, one database, one folder of attachments.
- Nothing to provision first: no cache, no search cluster, no queue, no object
  storage.
- SQLite for one person; PostgreSQL when several people use it at once.
- A backup is a database dump and a folder.

## Before you start

- **The Zotero desktop application is the only client.** The phone apps have
  the server address built in, so they cannot be pointed anywhere else.
  [Why, and why that will not
  change.](docs/motivation.md#the-precondition-everything-else-rests-on)
- **altero is not finished.** Use a test installation, not one holding a
  library you care about — syncing sends the client's data to it.
- **Zotero does not support this.** The setting that redirects the client is
  hidden and undocumented, and self-hosting has been declined upstream since
  2012. Nothing here can stop that setting disappearing in a future release.

## Quick start

You need Python 3.14 or newer and [uv](https://docs.astral.sh/uv/) — or
[Docker](#with-docker) instead.

**1. Start the server.** It listens on `http://127.0.0.1:8000`.

```sh
uv sync
cp config.example.py config.py
uv run alembic upgrade head
uv run altero user add <username>
uv run altero
```

**2. Point Zotero at it.** Open **Settings → Advanced → Config Editor**, accept
the warning, and set:

    extensions.zotero.api.url = http://localhost:8000/
    extensions.zotero.streaming.url = ws://localhost:8000/stream

Both matter: the second address is not redirected by the first, and a client
left at its default would hand your API key to zotero.org.

**3. Link the account.** Restart Zotero and open **Settings → Sync → Link
Account**. Zotero opens a browser page and waits for approval.

- If the [web interface](docs/web-interface.md) has been built — it is in the
  container image — that page is a sign-in form and approves the key itself.
- Otherwise, approve it from the shell:

  ```sh
  uv run altero login list                       # shows the pending request
  uv run altero login approve <token> <username>
  ```

Syncing starts the next time the client checks in.
[docs/clients.md](docs/clients.md) explains each step in more detail.

### With Docker

This brings up PostgreSQL, altero and a volume for attachments:

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
```

- The image is built from the checkout and database updates run on start, so
  upgrading is `git pull && docker compose up -d --build`.
- [docs/deployment.md](docs/deployment.md) covers settings, health checks, rate
  limiting, reverse proxies and upgrading PostgreSQL itself.

## What works

Everyday syncing, in both directions:

- Items, collections, tags and saved searches, with the safeguards that stop
  two clients overwriting each other.
- Every kind of item Zotero has, including notes, attachments and annotations.
- Attached files, uploaded and downloaded, with their text searchable.
- Group libraries, with the permissions that go with them, and My Publications.
- Who added an item to a group, and who last changed it.
- Live updates, so a change reaches a connected client at once instead of at
  its next check.

Finding things, and getting them out again:

- Search that looks inside attached PDFs and child notes, and answers with the
  item they belong to. It runs in the database rather than needing a search
  cluster alongside — [what that
  costs](docs/compatibility.md#quick-search-and-full-text-search).
- Citations and bibliographies in any published citation style.
- Export as BibTeX, BibLaTeX or RIS.
- Atom feeds of a library.

### Things zotero.org does not offer

Three things people have asked it for over the years and not got:

- **Tell me when a group changes.** A member can ask to hear about it, and
  hears once the library has been quiet for a while — a digest rather than a
  message per batch of a sync. Off until somebody turns it on.
- **What happened in this group.** A log of who changed what and when, naming
  the items and collections involved as they were called at the time, readable
  by every member rather than only administrators.
- **Renaming a tag in one go.** zotero.org has no way to do this at all, so a
  client has to rewrite every item carrying the tag itself. [Asked for since
  2016.](https://github.com/zotero/dataserver/issues/108)

### Not yet

- Export formats other than BibTeX, BibLaTeX and RIS.

[docs/status.md](docs/status.md) has the detailed list, feature by feature.

## The web interface

A browser application at `/app/`, in six languages. It covers:

- Registration, sign-in with an optional authenticator code, account settings
  and API keys.
- Notifications, group invitations, and a group's activity log.
- Browsing a library: collections, tags, search, an item's details, its
  attachments, and a citation in a style you pick.
- Making and removing collections, and renaming a tag throughout the library.

Everything else in a library it reads rather than changes. The sync API accepts
only an API key and refuses a browser session, so nothing the interface does
can reach the sync protocol — see
[docs/web-interface.md](docs/web-interface.md).

## Administration

Accounts, keys, groups and moving libraries are command-line operations:

```sh
uv run altero user add <username>
uv run altero key add <username> --name laptop
uv run altero library export user 1 library.zip
uv run altero library import library.zip
```

[docs/administration.md](docs/administration.md) is the full list. It also
covers moving a library between servers, and what to do after a database has
been recreated — the case where clients lock themselves out.

## Documentation

- [motivation.md](docs/motivation.md) — why this exists, and which of its goals
  are intentions rather than things the code already does
- [status.md](docs/status.md) — what works and what does not
- [clients.md](docs/clients.md) — connecting a Zotero client
- [deployment.md](docs/deployment.md) — running, configuring and upgrading it
- [administration.md](docs/administration.md) — accounts, keys, groups,
  libraries
- [email.md](docs/email.md) — what altero sends, and how to let it send
- [web-interface.md](docs/web-interface.md) — the browser application
- [compatibility.md](docs/compatibility.md) — every place altero deliberately
  differs from the original, and every quirk it copies on purpose
- [schema.md](docs/schema.md) — the database, against the original's

The target is the Zotero desktop application, so where zotero.org's published
documentation and its actual server disagree, the server wins — including its
inconsistencies.

## Development

```sh
uv sync
uv run pre-commit install  # once per checkout

uv run pytest              # run the test suite
uv run ruff format         # format
uv run ruff check --fix    # lint
uv run ty check            # type-check
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers how the code is laid out, how
behaviour is checked against the original server, and what a change is expected
to come with.

## License

[GNU Affero General Public License v3](LICENSE) or later.
