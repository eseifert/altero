# Getting started

This guide gets a local altero instance running and connects a **test** Zotero Desktop profile to it.

**Result:** Zotero Desktop is linked to a local altero server and can begin syncing.

> [!WARNING]
> altero is pre-stable software. Use a separate Zotero profile or a library you can recreate.

## 1. Start altero with Docker Compose

The image is published, so a checkout is optional. In an empty directory:

```sh
curl -fsSLO https://raw.githubusercontent.com/eseifert/altero/master/docker/compose.yaml
docker compose up -d
```

From a checkout of the repository, name the file where it lives instead:

```sh
docker compose -f docker/compose.yaml up -d
```

This starts PostgreSQL, altero and persistent attachment storage. The API is published on the loopback interface, on port 8000.

For a source installation instead, see [Deployment](deployment.md#from-a-source-checkout).

## 2. Create the first account

The first account administers the instance. Create it either way.

**In the browser.** Open <http://localhost:8000/app/> and register. Registration is open only while the instance has no accounts at all, so this works exactly once.

**From a shell.** Two commands, because `altero user add` sets no password:

```sh
docker compose exec altero altero user add <username>
docker compose exec altero altero user password <username>
```

> [!IMPORTANT]
> `altero user add` creates the account without a password, and creating it also closes browser registration. Run `altero user password` as well, unless the account will sign in through [single sign-on](deployment.md#single-sign-on) or a passkey.

## 3. Point Zotero Desktop at altero

In Zotero Desktop, open:

**Settings → Advanced → Config Editor**

Set:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

The trailing slash on `api.url` matters.

8000 is the port altero listens on inside the container (`ALTERO_PORT`), and the Compose file publishes it on the host under `ALTERO_PUBLISH_PORT`, also 8000. Change either and both URLs above move with it.

> [!IMPORTANT]
> Set the streaming URL as well as the API URL. Zotero resolves the streaming service separately. If the streaming URL is left at its built-in default, Zotero can send the altero API key to zotero.org, where it is not valid.

If you do not want streaming updates, disable them instead of leaving the default endpoint in place:

```text
extensions.zotero.streaming.enabled = false
```

Restart Zotero after changing these preferences.

## 4. Link the account

> [!WARNING]
> If this Zotero profile has synced before, with zotero.org or with another server, linking is refused: Zotero sends the account number its data directory remembers. See [A profile that has synced before](clients.md#a-profile-that-has-synced-before).

Open:

**Settings → Sync → Link Account**

Zotero opens altero in the browser. Sign in with the account you created and approve the client.

The desktop client receives an API key and begins using altero for synchronization.

## 5. Confirm that the instance is healthy

The readiness endpoint is:

```text
GET http://localhost:8000/health
```

A healthy instance returns a JSON response with `status: "ok"` plus version and database-revision information.

## 6. Test with disposable data

Create a few items, collections and attachments in the test profile and let them sync. For a stronger test, connect a second Zotero profile and follow [Syncing two desktop clients](testing-two-clients.md).

## What to read next

- [Connecting a Zotero client](clients.md) — the client settings and login flow in more detail.
- [Deployment](deployment.md) — TLS, PostgreSQL, upgrades, reverse proxies and production settings.
- [What works](status.md) — implemented and missing functionality.
- [Web interface](web-interface.md) — browser features for users and administrators.

## What this setup does not support

The official Zotero iOS and Android applications cannot be pointed at an alternate API host at runtime. altero therefore targets the unmodified desktop application, not the official mobile apps. See [Connecting a Zotero client](clients.md#mobile-apps-are-not-supported).
