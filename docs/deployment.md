# Deployment

This page covers running and operating altero. For a first local test, [Getting started](getting-started.md) is shorter.

## Choose how to run altero

| Method | Best for | Database |
| --- | --- | --- |
| Docker Compose | Easiest evaluation and normal self-hosting | PostgreSQL |
| Source checkout | Development or direct Python deployment | SQLite by default; PostgreSQL optional |

For a server used by several people, prefer PostgreSQL.

## Docker Compose

The image is published as `ghcr.io/eseifert/altero`, so running altero needs no checkout and no build. From a repository checkout:

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
```

Without one, the Compose file on its own is the deployment:

```sh
mkdir altero && cd altero
curl -fsSLO https://raw.githubusercontent.com/eseifert/altero/master/docker/compose.yaml
docker compose up -d
docker compose exec altero altero user add <username>
```

The stack contains PostgreSQL, altero and persistent attachment storage.

`latest` is the newest release, prereleases included. `ALTERO_IMAGE_TAG` selects another: a version such as `1.0.0-alpha.1` pins one release, and `dev` follows master.

The altero API is published on the loopback interface by default. Put a TLS terminator or reverse proxy in front of it rather than exposing the application port directly.

### Production settings to change first

Before putting real data on the instance:

1. Set a real `POSTGRES_PASSWORD`.
2. Set `ALTERO_PUBLIC_URL` to the URL users will actually open.
3. Terminate TLS in front of altero.
4. Decide whether outgoing email is required; see [Email](email.md).
5. If a reverse proxy forwards client addresses, configure `ALTERO_FORWARDED_ALLOW_IPS` correctly.

Container settings belong in **`docker/.env`**, beside `docker/compose.yaml`.

To see the values Compose resolved:

```sh
docker compose -f docker/compose.yaml config
```

### Upgrade altero

```sh
docker compose -f docker/compose.yaml pull altero
docker compose -f docker/compose.yaml up -d
```

An instance pinned with `ALTERO_IMAGE_TAG` upgrades when that value changes, not when `pull` runs.

Database migrations run when altero starts. If a migration fails, the application container exits instead of serving against an incompatible schema.

To update only the PostgreSQL image within the currently compatible major version:

```sh
docker compose -f docker/compose.yaml pull db
```

### Upgrade PostgreSQL across a major version

altero's migrations do not upgrade PostgreSQL's own on-disk data format.

Moving a PostgreSQL volume to a new major version requires a dump and restore, for example with `pg_dump` from the old server and `psql` into the new one. The PostgreSQL image will refuse an incompatible data directory rather than silently adopting it.

### Build the image instead of pulling it

A change to the source, the Dockerfile or the web interface wants a locally built image. `docker/compose.build.yaml` adds the build to the same deployment:

```sh
docker compose -f docker/compose.yaml -f docker/compose.build.yaml up -d --build
```

It builds `altero:local`, deliberately not the published name, so that a later `docker compose pull` cannot replace a built image without saying so. Both files carry the same project name, so the built stack uses the volumes an earlier pulled one wrote.

### What a small instance costs

Measured on x86-64 from a source checkout, Python 3.14 and SQLite, with the interface built:

| | |
| --- | --- |
| altero, idle after start | ~125 MB resident |
| altero, after light API traffic | ~130 MB resident |
| Peak during start-up and migration | ~133 MB resident |
| An empty database, schema only | 0.7 MB |
| The installed Python environment | ~380 MB |

The container runs the same interpreter and the same packages, so the application's own use is the figure above. Two things sit on top of it and are **not** measured here: the PostgreSQL container in the Compose stack, and the image on disk.

Attachments are what grows. They are stored once per digest, so a file two libraries hold is on disk once; a library's nominal and real usage are reported per library under **Administration → Storage**.

## From a source checkout

Requirements:

- Python 3.14 or newer;
- [uv](https://docs.astral.sh/uv/).

SQLite is the default. For PostgreSQL outside Docker, install the extra dependency:

```sh
uv sync --extra postgres
```

For a basic SQLite installation:

```sh
uv sync
cp config.example.py config.py
uv run alembic upgrade head
uv run altero user add <username>
uv run altero
```

The default address is:

```text
http://127.0.0.1:8000
```

You can create an API key directly if needed:

```sh
uv run altero key add <username> --name laptop
```

The key is printed once and cannot be displayed again.

## Health check

`GET /health` is the readiness endpoint and is also used by the container health check.

A successful response includes the application version, API version, schema version and database migration revision, for example:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "apiVersion": 3,
  "schemaVersion": 42,
  "revision": "c1b573deea88"
}
```

If the database is unavailable, the endpoint returns `503` with:

```json
{"status": "error"}
```

Because `/health` is unauthenticated, it intentionally does not expose the database failure details.

## Configuration

For a source installation, copy `config.example.py` to `config.py`.

Every setting can also be supplied as an `ALTERO_`-prefixed environment variable. Environment variables take precedence over the configuration file.

Example:

```sh
ALTERO_PORT=9000 ALTERO_DEBUG=true uv run altero
```

Set `ALTERO_CONFIG` if the configuration module lives at another path.

## Public URL

`ALTERO_PUBLIC_URL` should be the stable external URL of the instance, for example:

```text
https://altero.example.org
```

It becomes required in practice when you use features that generate callbacks or bind credentials to a host:

- OpenID Connect or SAML sign-in;
- passkeys;
- links in outgoing email.

Changing the **host** of `ALTERO_PUBLIC_URL` invalidates existing passkeys. Changing only the scheme or port does not.

## Outgoing email

Email uses:

- `ALTERO_SMTP_URL`;
- `ALTERO_MAIL_FROM`; and
- `ALTERO_PUBLIC_URL`.

Without an SMTP relay, most messages are written to the log instead. Self-service password reset is the exception: it is not enabled without a relay because a password-reset link must not be exposed in server logs.

See [Email](email.md) for relay URLs, Docker details, security notices and group digests.

## Single sign-on

OpenID Connect and SAML 2.0 providers are configured in **Administration → Sign-in providers**.

Set `ALTERO_PUBLIC_URL` first. The callback/redirect address shown in the administration screen is built from that value and must match the address registered with the identity provider.

See [Administration](administration.md#sign-in-providers).

## Group notifications

Group notifications are opt-in per member and per group.

Two settings control digest delivery:

```sh
ALTERO_GROUP_DIGEST_QUIET_PERIOD=900
ALTERO_GROUP_DIGEST_INTERVAL=60
```

`ALTERO_GROUP_DIGEST_INTERVAL=0` disables delivery. Activity is still recorded, so it can be delivered after the feature is re-enabled.

See [Email](email.md#group-notifications).

## Behind a reverse proxy

Without trusted forwarded headers, altero sees the proxy's address rather than the original client's address.

`ALTERO_FORWARDED_ALLOW_IPS` identifies proxies whose forwarded address headers altero may trust. This affects both rate limiting and the “last used from” address shown for API keys.

Only trust a proxy that **overwrites** forwarded-address headers. If a trusted proxy simply passes a client-supplied header through, the client can choose the address attributed to its request.

## Rate limiting

Rate limiting is off by default.

Example: allow 600 requests per 60 seconds per API key:

```sh
ALTERO_RATE_LIMIT=600 ALTERO_RATE_LIMIT_WINDOW=60 uv run altero
```

Requests over the limit receive `429` with a whole-second `Retry-After`, which Zotero understands.

Unauthenticated requests are counted per client address. `/health` is never rate limited.

The limiter is process-local. With several application workers, each process has its own allowance. Use the reverse proxy or another edge component if you need a deployment-wide defensive limit.

## Moving or restoring data

For whole-library export/import, migration from zotero.org and recovery after recreating a database, see [Administration](administration.md#library-transfer-and-recovery).
