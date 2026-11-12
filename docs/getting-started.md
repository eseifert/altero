# Getting started

This guide runs altero locally and connects a test Zotero Desktop profile.
For an existing server, go straight to [Connecting a Zotero client](clients.md).

> [!WARNING]
> This is the first release candidate for 1.0.0, ready for final testing before
> the stable release. Keep current backups of your libraries. Back up the server
> database and attachment storage together before upgrading.

## 1. Start altero

With Docker and Docker Compose installed, run:

```sh
mkdir altero && cd altero
curl -fsSLO https://raw.githubusercontent.com/eseifert/altero/master/docker/compose.yaml
docker compose up -d
```

This starts altero and PostgreSQL, with persistent storage. The server is
available only on your computer at <http://localhost:8000>.
The default image tag is `latest`, which includes prereleases.

For source installation, Podman, or a server other people can reach, see
[Deployment](deployment.md).

## 2. Create your account

Open <http://localhost:8000/app/> and register. The first account administers
the instance; public registration then closes unless an administrator enables it.
Claim this account before exposing a fresh instance publicly. For additional
users, operators can enable [verified-email requests and approval](administration.md#review-registration-requests).

Alternatively, create an account from the shell:

```sh
docker compose exec altero altero user add <username>
docker compose exec altero altero user password <username>
```

Run both commands: `user add` does not set a password.

## 3. Configure Zotero Desktop

In your test profile, open **Settings → Advanced → Config Editor** and set:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

Keep the trailing slash on the API URL. Restart Zotero.

> [!IMPORTANT]
> Set both URLs. Leaving the streaming URL unchanged can send your altero API key to zotero.org.

A profile that has already synced needs special care. Read
[A profile that has synced before](clients.md#a-profile-that-has-synced-before)
before connecting it.

## 4. Link the account

Open **Settings → Sync → Link Account** in Zotero. Sign in to altero in the
browser window that opens and approve the connection.

Create an item, a collection and an attachment in Zotero. Sync, then open
altero's browser interface to check that they arrived.

## Next steps

- [Connect a second client](testing-two-clients.md) to check synchronization in both directions.
- [Use the browser interface](web-interface.md) to manage your library.
- [Prepare a server for everyday use](deployment.md), including HTTPS and backups.
- [Check features and limits](status.md), including mobile-app support.
