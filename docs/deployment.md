# Deployment

This page covers running and operating altero. For a first local test, [Getting started](getting-started.md) is shorter.

## Choose how to run altero

| Method          | Best for                                   | Database                               |
|-----------------|--------------------------------------------|----------------------------------------|
| Docker Compose  | Easiest evaluation and normal self-hosting | PostgreSQL                             |
| Source checkout | Development or direct Python deployment    | SQLite by default; PostgreSQL optional |

For a server used by several people, prefer PostgreSQL.

## Database requirements

The bundled container meets the requirements. For a source installation:

- SQLite must support FTS5 with the trigram tokenizer. Migrations report an unsupported SQLite installation before proceeding.
- PostgreSQL needs the `pg_trgm` and `btree_gin` extensions, usually provided by its contrib package.

Migrations create the PostgreSQL extensions when the database user has
permission. Otherwise, ask the database administrator to run these in altero's
database:

```sql
CREATE EXTENSION pg_trgm;
CREATE EXTENSION btree_gin;
```

Index creation can make a large library's first migration take longer and use
additional disk space. A missing database feature stops the migration with an error.

## Docker Compose

The image is published as `ghcr.io/eseifert/altero`, so running altero needs no checkout and no build. The Compose file on its own is the deployment:

```sh
mkdir altero && cd altero
curl -fsSLO https://raw.githubusercontent.com/eseifert/altero/master/docker/compose.yaml
docker compose up -d
docker compose exec altero altero user add <username>
docker compose exec altero altero user password <username>
```

From a repository checkout, name the file where it lives instead:

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
docker compose -f docker/compose.yaml exec altero altero user password <username>
```

The stack contains PostgreSQL, altero and persistent attachment storage.

`altero user add` creates the account without a password, so `altero user password` follows it. The alternative is to create the first account in the browser: registration is open while the instance has no accounts at all, and the account that claims it administers the instance. See [Accounts](web/account.md).

The default `latest` image includes prereleases. For controlled upgrades, set
`ALTERO_IMAGE_TAG` to your chosen release tag in `.env` beside the Compose file.
Use `dev` only if you intend to follow development builds. The documentation
site's `latest` alias is managed separately from the container tag.

The altero API is published on the loopback interface by default. Put a TLS terminator or reverse proxy in front of it rather than exposing the application port directly.

The Compose stack publishes container port 8000 at host port 8000. Set `ALTERO_PUBLISH_PORT` to change the host port; leave `ALTERO_PORT` unchanged unless you also update the container mapping.

### Production settings to change first

Before putting real data on the instance:

1. Set a real `POSTGRES_PASSWORD`.
2. Set `ALTERO_PUBLIC_URL` to the URL users will actually open.
3. Terminate TLS in front of altero.
4. Decide whether outgoing email is required; see [Email](email.md).
5. Name the reverse proxy in `ALTERO_FORWARDED_ALLOW_IPS`; see [Behind a reverse proxy](#behind-a-reverse-proxy).

Put settings in **`.env` beside your Compose file**: `docker/.env` when using the repository layout.

To see the values Compose resolved:

```sh
docker compose -f docker/compose.yaml config
```

### Upgrade altero

1. Read the [changelog](https://github.com/eseifert/altero/blob/master/CHANGELOG.md) for changes between your installed and target releases. For older installations, also check [historical upgrade notes](release-history.md#historical-upgrade-notes).
2. Back up the database, attachment storage and configuration together; see [Backups](#backups).
3. Update `ALTERO_IMAGE_TAG` if you pinned the image, then pull and recreate the application:

   ```sh
   docker compose pull altero
   docker compose up -d
   ```

4. Check the logs and `/health`, then sync a test client before resuming normal use.

Run these commands beside a downloaded Compose file. In a repository checkout,
add `-f docker/compose.yaml` to each Compose command.

Migrations run automatically when the container starts. On failure, the
application exits instead of serving an incompatible database. Source
installations must update dependencies, rebuild the browser interface and run
`uv run alembic upgrade head` before restarting.

SMTP requires `ALTERO_PUBLIC_URL`; configure it before starting with email
enabled. Single sign-on and passkeys also depend on a stable public address.

Some older upgrades rebuild search indexes or rename stored files. Allow time
and free disk space. A rollback may require restoring **both** the database and
storage backup; running an older image alone is not a recovery plan.

### Upgrade PostgreSQL across a major version

altero's migrations do not upgrade PostgreSQL's own on-disk data format.

Moving a PostgreSQL volume to a new major version requires a dump and restore, for example with `pg_dump` from the old server and `psql` into the new one. The PostgreSQL image will refuse an incompatible data directory rather than silently adopting it.

### Build the image instead of pulling it

To deploy local changes, build an image using the additional Compose file: `docker/compose.build.yaml` adds the build to the same deployment:

```sh
docker compose -f docker/compose.yaml -f docker/compose.build.yaml up -d --build
```

The result is `altero:local`. It uses the same project and volumes as the pulled stack. Continue using both Compose files when operating a local build.

### Try the image on its own

For a quick single-user trial, the image runs without Compose or PostgreSQL:

```sh
docker run -d --name altero -p 127.0.0.1:8000:8000 -v altero-data:/data ghcr.io/eseifert/altero:latest
docker exec altero altero user add <username>
docker exec altero altero user password <username>
```

The SQLite database is kept on the `/data` volume, beside the attachments. `ALTERO_DATABASE_URL` selects another database, as the Compose stack does. For a server used by several people, use the Compose stack instead.

## Podman

The image runs under Podman unchanged. Three things differ from Docker.

**It runs as UID 10001.** `/data` inside the image belongs to that user. A named volume inherits the ownership; a bind mount arrives with the host's instead, and altero then cannot write attachments. Under rootless Podman, hand the directory to the mapped user before starting the container:

```sh
podman unshare chown -R 10001:10001 /srv/altero/storage
```

On SELinux systems, mount it with `:Z` so the container gets a matching label.

**The port is the one above.** The container's own health check follows `ALTERO_PORT`, so an instance that moves it stays healthy; publishing `8090:8000` on the host needs no `ALTERO_PORT` at all.

**The health check needs the Docker image format.** Podman reads a health check out of an image only in that format; an OCI image carries no such field, and `podman healthcheck run` then answers `has no defined healthcheck`. The published image uses the Docker format, but an image built locally does not unless it is asked to:

```sh
podman build --format docker -f docker/Dockerfile .
```

`podman-compose` runs `docker/compose.yaml` as it is. For Quadlet, a systemd unit or a NixOS `virtualisation.oci-containers` module, the settings are the ones [Configuration](configuration.md) lists, plus `ALTERO_DATABASE_URL` pointing at the PostgreSQL container over a shared network.

A worked NixOS example, with altero and PostgreSQL as `virtualisation.oci-containers` units on a shared Podman network, is posted in [Discussion #5](https://github.com/eseifert/altero/discussions/5#discussioncomment-18404764). It is one contributor's running configuration rather than a reference deployment.

For the tested configuration and its limits, see the
[recorded rootless Podman run](testing-podman.md#recorded-run).
Use the same procedure to contribute another result.

## From a source checkout

Requirements:

- A supported Python installation and [uv](https://docs.astral.sh/uv/). The required Python range and minimum uv release are declared in `pyproject.toml`.
- Node and npm to build the browser interface. Use the Node release selected by `web/.nvmrc`.
- A database meeting the [requirements above](#database-requirements).

Use current security updates for these tools.

Source installations also need ICU development libraries, `pkg-config` and a
C++ compiler to build PyICU, used for duplicate PDF matching. On Debian or
Ubuntu, install `libicu-dev pkg-config g++` before `uv sync`. The Docker image
includes the ICU runtime. See [PyICU's installation instructions](https://pypi.org/project/PyICU/)
for other systems.

SQLite is the default. For PostgreSQL outside Docker, install the extra dependency:

```sh
uv sync --extra postgres
```

Check out your chosen release tag before installing; the default branch contains development work. For a basic SQLite installation:

```sh
git clone https://github.com/eseifert/altero.git
cd altero
git checkout <release-tag>
uv sync --locked
npm --prefix web ci
npm --prefix web run build
cp config.example.py config.py
uv run alembic upgrade head
uv run altero user add <username>
uv run altero user password <username>
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

## What a small instance costs

Plan capacity for the application, database and growing attachment storage.
Memory use depends on traffic and library size; account for PostgreSQL
separately from the application process.

Attachment files are stored once per content digest even when several libraries
use them. **Administration → Storage** shows physical disk use, library totals
and missing files. Monitor free space and leave room for backups and migrations.

## Attachment storage

Use a normal filesystem that supports atomic renames for
`ALTERO_STORAGE_PATH`. Local disks and suitable NFS or SMB mounts can provide this.

> [!WARNING]
> Do not use object storage mounted through s3fs, goofys or rclone as the attachment directory. Uploads rely on atomic renames, which these mounts do not provide. Back up a filesystem-based store to object storage instead.

## Health check

`GET /health` returns `200` and `status: "ok"` when the database is reachable.
The response also reports the application, API and schema versions and migration
revision. Use it for readiness monitoring.

An unavailable database returns `503` with `{"status": "error"}`. Inspect the
server logs for details.

## Configuration

Settings come from three places, in increasing order of precedence: the built-in defaults, a `config.py` module, and `ALTERO_`-prefixed environment variables.

```sh
cp config.example.py config.py                  # a source installation
ALTERO_PORT=9000 ALTERO_DEBUG=true uv run altero  # or a one-off override
```

In the Compose stack, every `ALTERO_` setting in `docker/.env` reaches the container.

[Configuration](configuration.md) lists every setting with its default, and how to set it in each of those places.

## Public URL

`ALTERO_PUBLIC_URL` should be the stable external URL of the instance, for example:

```text
https://altero.example.org
```

API object links and attachment upload/download URLs use this address, including
its HTTPS scheme, even when a reverse proxy connects to altero over HTTP. When
it is unset, those URLs use the request's address instead.

It becomes required in practice when you use features that generate callbacks or bind credentials to a host:

- OpenID Connect or SAML sign-in;
- passkeys;
- the authorization server, which refuses to serve its endpoints rather than guess the `iss` claim — see [Connecting other applications](oauth.md);
- SMTP, which refuses to start without it so account links cannot use an untrusted request host.

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

Configure your proxy to:

- Accept attachment uploads at least as large as `ALTERO_MAX_UPLOAD_MB` (1 GiB by default). A smaller proxy limit produces `413` errors.
- Pass WebSocket upgrades for `/stream`, used by Zotero Desktop.
- Stream `/web/libraries/<id>/events` without buffering, used for live browser updates. Allow idle connections for at least a minute.
- Preserve altero's security headers and cache controls. Do not cache `/app/sw.js` or `/app/manifest.webmanifest` beyond their revalidation rules.
- Pass the external `Host`, and overwrite `X-Forwarded-For` with the actual client address.

Set `ALTERO_PUBLIC_URL` to the external HTTPS address. Set
`ALTERO_FORWARDED_ALLOW_IPS` to the connecting proxy's address so client IPs
and schemes are recognized. Trust only a proxy that overwrites client-supplied
forwarded headers. In a container network, this is usually a network address,
not `127.0.0.1`.

Run a **single application process** when using live updates: the desktop and
browser notification brokers are process-local.

The examples below show routing. Configure your TLS certificates and security
policy, including HSTS, at the proxy.

### nginx

```nginx
server {
    listen 443 ssl;
    server_name zotero.example.org;

    # Attachments. The default is 1m, which rejects most PDFs with 413.
    client_max_body_size 1024m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        # Overwritten, not appended: $proxy_add_x_forwarded_for would carry a
        # client-supplied header through, and altero believes this one.
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # The streaming API. Same upstream, but the upgrade has to be passed on
    # explicitly and the connection lives longer than a request.
    location /stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }
}
```

### Caddy

```caddy
zotero.example.org {
    reverse_proxy 127.0.0.1:8000 {
        # Caddy appends the client to an X-Forwarded-For it was handed;
        # replacing it is what makes trusting the header safe.
        header_up X-Forwarded-For {remote_host}
    }
}
```

Caddy needs nothing said about WebSockets or body size: it passes an upgrade through as it stands and imposes no limit of its own.

### Traefik

```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.altero.rule=Host(`zotero.example.org`)
  - traefik.http.routers.altero.entrypoints=websecure
  - traefik.http.routers.altero.tls.certresolver=letsencrypt
  - traefik.http.services.altero.loadbalancer.server.port=8000
```

Traefik proxies the WebSocket without configuration and imposes no body limit. It replaces `X-Forwarded-For` with the address the connection came from unless `forwardedHeaders.trustedIPs` is set on the entry point, which is the behavior to keep.

Reaching altero by container name means both containers share a network, and the `ports:` publication in `docker/compose.yaml` is then unnecessary — remove it rather than exposing the application port beside the proxy.

### Tailscale

```sh
tailscale serve --bg 8000
```

`tailscale serve` terminates TLS for the machine's tailnet name, passes `Host` through, and sets `X-Forwarded-Proto` and `X-Forwarded-For` itself rather than appending to what the client sent. It connects from `127.0.0.1`, so:

```sh
ALTERO_FORWARDED_ALLOW_IPS=127.0.0.1
ALTERO_PUBLIC_URL=https://<machine>.<tailnet>.ts.net
```

Under Docker Compose, altero sees the Docker network's gateway instead of `127.0.0.1`; the access log shows the address to name.

## Rate limiting

The optional general request limiter is off by default. Password and
second-factor sign-in have separate, always-on protection described below.

Example: allow 600 requests per 60 seconds per API key:

```sh
ALTERO_RATE_LIMIT=600 ALTERO_RATE_LIMIT_WINDOW=60 uv run altero
```

Requests over the limit receive `429` with a whole-second `Retry-After`, which Zotero understands.

Unauthenticated requests are counted per client address. So are requests with a key that has not authenticated in the current window, as well as per key: made-up keys share their address's allowance. `/health` is never rate limited.

The limiter is process-local. With several application workers, each process has its own allowance. Use the reverse proxy or another edge component if you need a deployment-wide defensive limit.

### Sign-in backoff

Password and second-factor guesses have always-on protection shared across
workers and restarts. The first five account attempts and twenty address
attempts can proceed without waiting. Further guesses cause increasing pauses,
up to five minutes. Responses include `429` and `Retry-After`; a quiet period
of fifteen minutes resets the counters.

Username and email share the same account budget; changing aliases or requesting
another code does not bypass it. Passkey and institutional sign-in do not use
these password/code budgets.

Configure [forwarded headers](#behind-a-reverse-proxy) correctly so users behind
a proxy are not all counted as one client address.

## Moving or restoring data

For whole-library export/import, migration from zotero.org and recovery after recreating a database, see [Administration](administration.md#library-transfer-and-recovery).

## Backups

Keep the database and attachment storage as one consistent backup. Stop altero
and other writers while taking it; for Compose, stop the application with
`docker compose -f docker/compose.yaml stop altero` and leave PostgreSQL running.
Use `pg_dump` for PostgreSQL, or copy the SQLite database while altero is stopped,
and copy the attachment storage before restarting the application.

Keep configuration and the secrets needed to operate the instance with the
backup. Test a restore in a separate instance before relying on it. A
[library archive](administration.md#library-transfer-and-recovery) preserves
one library's data and files; it does not contain instance accounts or API keys.
