# Getting started

This guide gets a local altero instance running and connects a **test** Zotero Desktop profile to it.

**Audience:** first-time users and evaluators  
**Result:** Zotero Desktop is linked to a local altero server and can begin syncing.

> [!WARNING]
> altero is pre-stable software. Use a separate Zotero profile or a library you can recreate.

## 1. Start altero with Docker Compose

From a checkout of the repository:

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
```

This starts PostgreSQL, altero and persistent attachment storage. The API is published on the loopback interface by default.

For a source installation instead, see [Deployment](deployment.md#from-a-source-checkout).

## 2. Point Zotero Desktop at altero

In Zotero Desktop, open:

**Settings → Advanced → Config Editor**

Set:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

The trailing slash on `api.url` matters.

> [!IMPORTANT]
> Set the streaming URL as well as the API URL. Zotero resolves the streaming service separately. If the streaming URL is left at its built-in default, Zotero can send the altero API key to zotero.org, where it is not valid.

If you do not want streaming updates, disable them instead of leaving the default endpoint in place:

```text
extensions.zotero.streaming.enabled = false
```

Restart Zotero after changing these preferences.

## 3. Link the account

Open:

**Settings → Sync → Link Account**

Zotero opens altero in the browser. Sign in with the account you created and approve the client.

The desktop client receives an API key and begins using altero for synchronization.

## 4. Confirm that the instance is healthy

The readiness endpoint is:

```text
GET http://localhost:8000/health
```

A healthy instance returns a JSON response with `status: "ok"` plus version and database-revision information.

## 5. Test with disposable data

Create a few items, collections and attachments in the test profile and let them sync. For a stronger test, connect a second Zotero profile and follow [Syncing two desktop clients](testing-two-clients.md).

## What to read next

- [Connecting a Zotero client](clients.md) — the client settings and login flow in more detail.
- [Deployment](deployment.md) — TLS, PostgreSQL, upgrades, reverse proxies and production settings.
- [What works](status.md) — implemented and missing functionality.
- [Web interface](web-interface.md) — browser features for users and administrators.

## What this setup does not support

The official Zotero iOS and Android applications cannot be pointed at an alternate API host at runtime. altero therefore targets the unmodified desktop application, not the official mobile apps. See [Connecting a Zotero client](clients.md#mobile-apps-are-not-supported).
