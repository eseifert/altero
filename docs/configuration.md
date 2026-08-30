# Configuration

Every altero setting has a working default. A personal instance needs `ALTERO_PUBLIC_URL` and nothing else; the rest exist for deployments that need them.

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

`docker/.env`, beside `docker/compose.yaml`, holds the settings the Compose file passes through:

```sh
POSTGRES_PASSWORD=a-real-password
ALTERO_PUBLIC_URL=https://zotero.example.org
ALTERO_SMTP_URL=smtp://mail.example.org:587
ALTERO_MAIL_FROM=zotero@example.org
ALTERO_IMAGE_TAG=1.0.0-alpha.2
ALTERO_PUBLISH_PORT=8000
```

> [!WARNING]
> Only those reach the container. Compose reads `.env` to fill in the variables the file itself mentions, so `ALTERO_RATE_LIMIT=600` in `docker/.env` changes nothing at all — and says nothing about it either.

Anything else needs an entry in the service's `environment:`. Put it in a second Compose file rather than editing `compose.yaml`, which is replaced on upgrade:

```yaml
# docker/compose.settings.yaml
services:
  altero:
    environment:
      ALTERO_OPEN_REGISTRATION: "true"
      ALTERO_RATE_LIMIT: "600"
      ALTERO_FORWARDED_ALLOW_IPS: "172.18.0.2"
```

```sh
docker compose -f docker/compose.yaml -f docker/compose.settings.yaml up -d
```

`docker compose ... config` prints the merged result, which is the reliable way to see what the container will actually be given:

```sh
docker compose -f docker/compose.yaml -f docker/compose.settings.yaml config
```

The image sets `ALTERO_STORAGE_PATH=/data/storage`, `ALTERO_HOST=0.0.0.0` and `ALTERO_PORT=8000` itself. `/data` is the volume, so leave the storage path alone unless you also move the mount.

## Values

Booleans accept `true`, `1`, `yes` and `on`, and their opposites, in any case. Durations are whole seconds, hours or days as the name says. An empty string is a real value and usually means "off" or "fall back": `ALTERO_SMTP_URL=` writes mail to the log.

## Server and storage

| Setting               | Default                             | What it does                                                                                 |
|-----------------------|-------------------------------------|----------------------------------------------------------------------------------------------|
| `ALTERO_DATABASE_URL` | `sqlite+aiosqlite:///altero.sqlite` | SQLAlchemy URL. The driver must be an async one: `sqlite+aiosqlite` or `postgresql+asyncpg`. |
| `ALTERO_HOST`         | `127.0.0.1`                         | Interface to bind. The container sets `0.0.0.0`.                                             |
| `ALTERO_PORT`         | `8000`                              | Port to bind, 1–65535.                                                                       |
| `ALTERO_STORAGE_PATH` | `./storage`                         | Directory holding attachment files. The container sets `/data/storage`.                      |
| `ALTERO_DEBUG`        | `false`                             | Debug behavior, SQL echoing and auto-reload. Never enable in production.                     |

## Accounts

| Setting                    | Default | What it does                                                                                                                                                                                                                                                           |
|----------------------------|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ALTERO_OPEN_REGISTRATION` | `false` | Whether anybody may register from the browser. The first account is always allowed, and so is anybody holding an unanswered group invitation, so a fresh instance is reachable without shell access either way.                                                        |
| `ALTERO_PASSWORD_RESET`    | `false` | Whether somebody who has forgotten their password may ask for a link. It makes the mail relay part of the authentication, does nothing without `ALTERO_SMTP_URL`, and nothing for an unconfirmed address. An administrator can issue the same link whatever this says. |

## Public URL and email

| Setting             | Default            | What it does                                                                                                                                                                                |
|---------------------|--------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ALTERO_PUBLIC_URL` | *(empty)*          | The stable external URL of the instance. Required for single sign-on, passkeys and the authorization server, each of which refuses to guess it. See [Public URL](deployment.md#public-url). |
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
| `ALTERO_TRASH_RETENTION_DAYS`    | `0`     | How long an item stays in the trash before the server deletes it for good. zotero.org uses 30.                                                       |
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
| `ALTERO_IMAGE_TAG`       | `docker/compose.yaml`    | Which published image to run: `latest`, a release such as `1.0.0-alpha.2`, or `dev` for master. |
| `ALTERO_PUBLISH_PORT`    | `docker/compose.yaml`    | Loopback port the API is published on.                                                          |
| `POSTGRES_PASSWORD`      | `docker/compose.yaml`    | Password for the bundled PostgreSQL, used by both containers.                                   |
