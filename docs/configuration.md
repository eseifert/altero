# Configuration

Use this reference to look up a setting and its default. For a new server, start with [Deployment](deployment.md#production-settings-to-change-first).

## Where a setting comes from

Three sources, in increasing order of precedence:

1. the built-in defaults listed below
2. `config.py`, a Python module of uppercase names
3. `ALTERO_`-prefixed environment variables

The name is the same in both places: `PUBLIC_URL` in `config.py` is `ALTERO_PUBLIC_URL` in the environment. The tables below give the environment form, because that is what a container takes.

A misspelled name in `config.py` stops the server with `Unknown setting`. A misspelled environment variable is ignored, the environment being a namespace altero does not own.

## From a source checkout

Copy the example and edit it:

```sh
cp config.example.py config.py
```

`config.py` is ignored by git, so local settings stay out of the repository. Point `ALTERO_CONFIG` at another path to load a configuration module from somewhere else.

For a one-off change, set the variable on the command line instead:

```sh
ALTERO_PORT=9000 ALTERO_DEBUG=true uv run altero
```

## In Docker

Put `.env` beside your Compose file: `docker/.env` for the repository layout, or `.env` beside a downloaded `compose.yaml`. Every `ALTERO_` setting in it reaches the container:

```sh
POSTGRES_PASSWORD=a-real-password
ALTERO_PUBLIC_URL=https://zotero.example.org
ALTERO_SMTP_URL=smtp://mail.example.org:587
ALTERO_MAIL_FROM=zotero@example.org
ALTERO_OPEN_REGISTRATION=true
ALTERO_RATE_LIMIT=600
```

The file is handed to the container whole, so keep out of it anything the application should not hold. `ALTERO_IMAGE_TAG` and `ALTERO_PUBLISH_PORT` belong there too, though they are read by Compose rather than by altero.

No `.env` is needed at all: an instance running on the defaults never writes one.

A variable exported in the shell wins over the file for `ALTERO_SMTP_URL`, `ALTERO_MAIL_FROM`, `ALTERO_PUBLIC_URL` and `ALTERO_SSO_ONLY`, which `compose.yaml` names itself. `ALTERO_DATABASE_URL` is always the stack's own database; point altero at an external one with a second Compose file rather than with `.env`:

```yaml
# docker/compose.settings.yaml
services:
  altero:
    environment:
      ALTERO_DATABASE_URL: postgresql+asyncpg://user:password@db.example.org:5432/altero
```

```sh
docker compose -f docker/compose.yaml -f docker/compose.settings.yaml up -d
```

`docker compose ... config` prints the merged result, which is how to see what the container will actually be given:

```sh
docker compose -f docker/compose.yaml config
```

The image sets `ALTERO_STORAGE_PATH=/data/storage`, `ALTERO_HOST=0.0.0.0` and `ALTERO_PORT=8000` itself. `/data` is the volume, so leave the storage path alone unless you also move the mount.

Without `ALTERO_DATABASE_URL`, as when the image runs [on its own](deployment.md#try-the-image-on-its-own), the database is SQLite at `/data/altero.sqlite`. That default comes from the image's own `/app/config.py`. A `config.py` mounted there replaces it.

## Values

Booleans accept `true`, `1`, `yes` and `on`, and their opposites, in any case. Durations are whole seconds, hours or days as the name says. An empty string is a real value and usually means "off" or "fall back": `ALTERO_SMTP_URL=` writes mail to the log.

## Server and storage

| Setting                        | Default                             | What it does                                                                                             |
|--------------------------------|-------------------------------------|----------------------------------------------------------------------------------------------------------|
| `ALTERO_DATABASE_URL`          | `sqlite+aiosqlite:///altero.sqlite` | SQLAlchemy URL. The driver must be an async one: `sqlite+aiosqlite` or `postgresql+asyncpg`.             |
| `ALTERO_DATABASE_POOL_SIZE`    | `5`                                 | Database connections kept open for requests to share.                                                    |
| `ALTERO_DATABASE_MAX_OVERFLOW` | `10`                                | Further connections opened when the pool is exhausted. A request waiting longer than 30 s for one fails. |
| `ALTERO_HOST`                  | `127.0.0.1`                         | Interface to bind. The container sets `0.0.0.0`.                                                         |
| `ALTERO_PORT`                  | `8000`                              | Port to bind, 1–65535.                                                                                   |
| `ALTERO_STORAGE_PATH`          | `./storage`                         | Directory holding attachment files. The container sets `/data/storage`.                                  |
| `ALTERO_MAX_UPLOAD_MB`         | `1024`                              | Largest attachment file accepted, in MiB, from a sync client or the browser. Larger uploads get `413`.   |
| `ALTERO_DEBUG`                 | `false`                             | Debug behavior, SQL echoing and auto-reload. Never enable in production.                                 |

## Accounts

| Setting                    | Default | What it does                                                                                                                                                                                                                                                           |
|----------------------------|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ALTERO_OPEN_REGISTRATION` | `false` | Whether anybody may register from the browser. First-account and invited-address registration are also available, except in SSO-only mode.                                                        |
| `ALTERO_REGISTRATION_APPROVAL` | `false` | Require mailbox proof and administrator approval for additional local accounts. Requires SMTP/public URL; incompatible with SSO-only mode. Open registration still controls general applications; invitations open a gated application, never direct admission. |
| `ALTERO_REGISTRATION_DOMAINS` | `[]` | Exact allowed ASCII mailbox domains; subdomains must be listed. Empty permits any valid domain. Environment values are JSON arrays. |
| `ALTERO_REGISTRATION_MAX_PENDING` | `1000` | Instance-wide cap on live pending applications. |
| `ALTERO_REGISTRATION_IP_LIMIT` | `5` | Submission attempts per source address/hour. Configure trusted proxy addresses correctly. |
| `ALTERO_REGISTRATION_GLOBAL_LIMIT` | `100` | Instance-wide submission attempts/hour, including recovery/duplicate attempts. Recipient mail remains capped at one/minute and five/day. |
| `ALTERO_PASSWORD_MIN_LENGTH` | `8` | Minimum length for new passwords, from 8 to 1024 characters. Existing passwords can still sign in. |
| `ALTERO_PASSWORD_BLOCK_COMMON` | `true` | Refuse common passwords using the bundled offline list; no composition rules or periodic resets. |
| `ALTERO_PASSWORD_RESET`    | `false` | Offer self-service password reset for confirmed addresses. Requires SMTP and a public URL. Administrators can issue reset links independently, except in SSO-only mode. |
| `ALTERO_SSO_ONLY` | `false` | Require configured OIDC/SAML providers for browser authentication and recent SSO proof for sensitive actions. Disables local credentials, registration, recovery, email changes and MFA; requires `ALTERO_PUBLIC_URL`. See [SSO-only mode](administration.md#sso-only-mode). |

The common-password list is bundled from
[Django 5.2](https://github.com/django/django/blob/5.2/django/contrib/auth/common-passwords.txt.gz)
under its BSD license (distributed beside the list in the Python package).
It contains 19,640 entries and is checked offline; no password is sent to another
service. SHA-256 of the pinned gzip file:
`3c1baed62596de36860824eb3f436d5932d37ca8b06e59df78f5a44ec175afe4`.
The comparison ignores case and outer whitespace, but accepted passwords are
hashed exactly as entered. Updating the policy does not invalidate existing
passwords or require periodic password changes.
Registration, account changes, administrator-issued passwords and reset links
use the same policy. A refused password leaves a reset link usable. Browser
registration and account password forms read the configured minimum from
`/web/config`.

## Public URL and email

| Setting             | Default            | What it does                                                                                                                                                                                |
|---------------------|--------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ALTERO_PUBLIC_URL` | *(empty)*          | The stable external URL for API object links, file transfers and email links. Required for SMTP, single sign-on, passkeys and the authorization server. See [Public URL](deployment.md#public-url). |
| `ALTERO_SMTP_URL`   | *(empty)*          | Relay for outgoing mail, as `smtp://[user:password@]host[:port]` or `smtps://…`. Empty writes messages to the log. See [Email](email.md).                                                   |
| `ALTERO_MAIL_FROM`  | `altero@localhost` | From address on outgoing mail. Set it to something the relay will send as.                                                                                                                  |

## Rate limiting and proxies

| Setting                      | Default   | What it does                                                                                                                                                                                                                          |
|------------------------------|-----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ALTERO_RATE_LIMIT`          | `0`       | Requests allowed per API key, or per address when unauthenticated, in each window. Zero disables the limit. See [Rate limiting](deployment.md#rate-limiting).                                                                         |
| `ALTERO_RATE_LIMIT_WINDOW`   | `60`      | Length of that window, in seconds.                                                                                                                                                                                                    |
| `ALTERO_FORWARDED_ALLOW_IPS` | *(empty)* | Proxies whose `X-Forwarded-For` and `X-Forwarded-Proto` may be believed, comma separated, or `*` for any peer. Only ever name a proxy that overwrites the header. See [Behind a reverse proxy](deployment.md#behind-a-reverse-proxy). |

## Retention

The first three are also settable in **Administration → Retention**, and a value stored there wins over the value configured here. Zero means never. See [Retention](administration.md#retention).

| Setting                          | Default | What it does                                                                                                                                         |
|----------------------------------|---------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ALTERO_TRASH_RETENTION_DAYS`    | `0`     | Days before permanent trash deletion; zero keeps trash indefinitely.                                                       |
| `ALTERO_ACTIVITY_RETENTION_DAYS` | `0`     | How long delivered group activity is kept.                                                                                                           |
| `ALTERO_UPLOAD_RETENTION_HOURS`  | `24`    | How long an authorized upload whose bytes never arrived is remembered. Nothing is lost by forgetting one; the client asks again.                     |
| `ALTERO_RETENTION_INTERVAL`      | `0`     | How often, in seconds, to apply those periods. Zero means only `altero retention run` ever does. 3600 suits an instance that should not need asking. |

## Group notifications

Nobody is subscribed until they ask, so these change nothing on an instance where no member has opted in. See [Group notifications](email.md#group-notifications).

| Setting                            | Default | What it does                                                                                                                                                          |
|------------------------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ALTERO_GROUP_DIGEST_QUIET_PERIOD` | `900`   | How long a group library must stop changing, in seconds, before what happened in it goes out. This is what turns one sync into one message rather than one per batch. |
| `ALTERO_GROUP_DIGEST_INTERVAL`     | `60`    | How often, in seconds, to look for activity that has settled. Zero turns group notifications off; activity is still recorded.                                         |

## Variables that are not settings

These are read by something other than the application's own configuration, so they have no `config.py` equivalent.

| Variable                 | Read by                  | What it does                                                                                    |
|--------------------------|--------------------------|-------------------------------------------------------------------------------------------------|
| `ALTERO_CONFIG`          | the application          | Path to the configuration module, if not `config.py` at the repository root.                    |
| `ALTERO_SKIP_MIGRATIONS` | the container entrypoint | `1` starts the server without running `alembic upgrade head` first.                             |
| `ALTERO_IMAGE_TAG`       | `docker/compose.yaml`    | Which published image to run: `latest`, a chosen release tag, or `dev` for master. |
| `ALTERO_PUBLISH_PORT`    | `docker/compose.yaml`    | Loopback port the API is published on.                                                          |
| `POSTGRES_PASSWORD`      | `docker/compose.yaml`    | Password for the bundled PostgreSQL, used by both containers.                                   |
