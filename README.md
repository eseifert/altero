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

It is meant to be small to look after: one server process, one database, one
folder of attachments. Nothing to provision first — no cache, no search
cluster, no queue, no object storage. SQLite for one person, PostgreSQL when
several people use it at once. A backup is a database dump and a folder.

And it is not only a copy of what zotero.org runs — see [what zotero.org does
not offer](#what-zoteroorg-does-not-offer).

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

Everyday syncing, in both directions: items, collections, tags and saved
searches, every kind of item Zotero has, attached files with their text
searchable, group libraries and My Publications, and live updates that reach a
connected client at once.

Finding things and getting them out again: search inside attached PDFs and
child notes, citations and bibliographies in any published style, export as
BibTeX, BibLaTeX or RIS, and Atom feeds of a library.

Not yet: the export formats beyond those three.
[docs/status.md](docs/status.md) has the list, feature by feature.

## What zotero.org does not offer

Things people have asked it for over the years and not got, which a server of
your own is in a position to answer:

- **Sign in with your organisation's directory** — OpenID Connect or SAML 2.0,
  asked for repeatedly and unsupported upstream. It signs you in to the
  browser; a Zotero client still uses an API key.
  [How to set one up.](docs/administration.md#sign-in-providers)
- **Share a collection, not a whole library** — [asked for since
  2008](https://forums.zotero.org/discussion/21217/), and answered as a link
  anybody can open, no account needed.
  [Why a link and not sync.](docs/web-interface.md#sharing-one)
- **Finer roles in a group** — [asked for since
  2010](https://forums.zotero.org/discussion/14053/): a member who can only
  read, one who can add but not delete, one who can edit only their own items.
  [How they behave.](docs/compatibility.md#finer-roles-for-one-member)
- **Hear when a group changes**, and read a log of what happened in it — for
  every member rather than only administrators.
- **Rename a tag in one go** — [asked for since
  2016](https://github.com/zotero/dataserver/issues/108); zotero.org has no way
  to do this at all.
- **Decide how long things are kept**, rather than living with a trash emptied
  after 30 days. [Retention.](docs/administration.md#retention)
- **See what a library costs on disk**, real usage against nominal, which
  zotero.org cannot report.
- **Take your library with you** — altero copies your personal library out of
  zotero.org with every key and version intact, so a client that had synced
  there carries on where it left off.
  [Moving in.](docs/web-interface.md#moving-in-from-zoteroorg)

## The web interface

A browser application at `/app/`, in six languages: registering and signing in,
account settings and API keys, browsing a library with its collections, tags,
search, item details and citations, filing and trashing items, sharing a
collection by link, renaming a tag, publishing to My Publications, running a
group, and moving a library in from zotero.org or a backup out. Editing an
item's fields is still the desktop client's job.

Signing in takes a password with an optional second factor — an authenticator
app or a code by email — a passkey, or your organisation's directory. None of
that reaches the sync API, which authenticates by API key and nothing else.

[docs/web-interface.md](docs/web-interface.md) covers all of it.

## Administration

One account administers the instance, and it is the only permission here that
is not per library. It grants nothing over anybody's library: an administrator
counts and measures, and cannot read a title, a note or a file they were not
already entitled to. In the browser that account gets five screens — overview,
storage, accounts, sign-in providers and retention.

The same things, and the ones that have no screen, are command-line
operations:

```sh
uv run altero user add <username>
uv run altero user admin <username>            # hand the role on
uv run altero key add <username> --name laptop
uv run altero group permission 1 grace read    # what one member may do
uv run altero library export user 1 library.zip
uv run altero library import library.zip
uv run altero retention run --dry-run
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
  libraries, moving one in from zotero.org
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
