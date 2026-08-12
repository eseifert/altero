# Running altero

## Requirements

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)

SQLite is the default and needs nothing further. For PostgreSQL outside a
container, install the driver with the `postgres` extra: `uv sync --extra
postgres`.

## From a source checkout

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

## In a container

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
```

That is PostgreSQL, altero and a volume for attachments. Everything the
container needs lives in `docker/`; run the commands from the repository root,
or `export COMPOSE_FILE=docker/compose.yaml` once and drop the `-f`.

The image is built from the checkout — nothing publishes one — so an upgrade is
a `git pull` and a rebuild:

```sh
git pull
docker compose -f docker/compose.yaml up -d --build
```

`--build` is the part that matters. Without it `up -d` finds the image it
already built and starts that, so the new code never runs; and `docker compose
pull` does not stand in for it, because there is no altero image to fetch. It
says so — `altero Skipped - No image to be pulled` — and then exits 0, having
updated PostgreSQL's image and nothing else. Use it when that is what you mean:

```sh
docker compose -f docker/compose.yaml pull db
```

Migrations run on start, so there is nothing else to remember; a failed
migration exits the container rather than serving against a schema it does not
understand.

The API is published on the loopback interface only — put a TLS terminator in
front of it rather than exposing it directly. `ALTERO_PUBLISH_PORT` moves it,
and `POSTGRES_PASSWORD` should be set to something other than its default
before anything real goes in.

Settings for the container go in **`docker/.env`**, beside the compose file
rather than at the repository root — that is where Compose looks, whichever
directory the command was run from, and `.env` is ignored by git so a password
in it stays local. `docker compose -f docker/compose.yaml config` prints what
the settled values actually are, which is the quick way to see that one
arrived. Outgoing mail is configured the same way; see [email.md](email.md).

### Upgrading PostgreSQL itself

Migrations on start cover altero's own schema, not PostgreSQL's. The database
is pinned to PostgreSQL 18, and moving a volume across a major version of
PostgreSQL is a dump and restore — the image refuses to start on a data
directory written by an older one, naming the version that wrote it, rather
than adopting it. `pg_dump` against the old container and `psql` into the new
one is the whole of it.

`altero library export` moves a library between instances, but not the users
and keys that own it; see [administration.md](administration.md).

## Health

`GET /health` is the readiness probe, and is what the container's own
`HEALTHCHECK` polls:

```json
{"status": "ok", "version": "0.1.0", "apiVersion": 3, "schemaVersion": 42,
 "revision": "c1b573deea88"}
```

`revision` is the migration the database is stamped with, which is the question
worth asking during an upgrade. It answers `503` with nothing but
`{"status": "error"}` when the database cannot be reached: the endpoint needs
no credentials, so it says nothing about why.

## Configuration

Copy `config.example.py` to `config.py` and edit it. Every setting can also be
supplied as an `ALTERO_`-prefixed environment variable, which takes precedence
over the file:

```sh
ALTERO_PORT=9000 ALTERO_DEBUG=true uv run altero
```

Set `ALTERO_CONFIG` to load a configuration module from another path.

## Outgoing mail

Confirmations, invitations and security notices need a relay:
`ALTERO_SMTP_URL`, `ALTERO_MAIL_FROM` and `ALTERO_PUBLIC_URL`. Without one they
are written to the log instead, which is deliberate — it is how the owner of a
fresh container reads the confirmation link and finishes registering. See
[email.md](email.md).

The one message that does **not** fall back to the log is a self-service
password reset. `ALTERO_PASSWORD_RESET` puts "forgotten your password?" on the
sign-in page, and it does nothing at all without a relay configured: a link
that sets a password, written to a log, is one anybody who can read the log can
follow. It is off by default either way, because it makes the mailbox part of
the authentication. An administrator can issue the same link from
**Administration → Accounts** on any instance.

## Group notifications

A member of a group library can ask to be told when it changes. Nobody is
subscribed by default, so on most instances there is nothing to configure and
nothing is sent.

Two settings decide the pacing, and a sweep runs inside the server process to
apply them:

```sh
ALTERO_GROUP_DIGEST_QUIET_PERIOD=900   # wait this long after the last change
ALTERO_GROUP_DIGEST_INTERVAL=60        # look this often; 0 disables entirely
```

`ALTERO_GROUP_DIGEST_INTERVAL=0` turns the feature off outright: nothing is
sent and nothing is shown, though activity is still recorded, so turning it
back on later delivers what accumulated rather than losing it.

Unlike the streaming API, this is safe behind several workers. The sweep claims
what it is about to send in the database, so one digest goes out however many
processes are running. See
[email.md](email.md#group-notifications).

## Behind a reverse proxy

The address altero records and counts is the proxy's until
`ALTERO_FORWARDED_ALLOW_IPS` names it. That one setting decides both what the
rate limiter counts and what is shown as an API key's last-used address.

Only name a proxy that overwrites the header it forwards. Naming one that
passes a client-supplied header through lets a caller choose which address is
attributed to it.

## Rate limiting

Off by default, because a personal instance has nothing to throttle and a limit
nobody asked for turns a working sync into a stuck one. To allow, say, 600
requests a minute per API key:

```sh
ALTERO_RATE_LIMIT=600 ALTERO_RATE_LIMIT_WINDOW=60 uv run altero
```

A caller over its allowance gets `429` with `Retry-After` in whole seconds,
which is what the client pauses on. Unauthenticated requests are counted per
address, and `/health` is never limited.

The count lives in the serving process, so behind several workers each keeps
its own and the real allowance is that many times the configured one. It is
there to stop a runaway client, not a determined one; that belongs in whatever
terminates TLS in front of altero.
