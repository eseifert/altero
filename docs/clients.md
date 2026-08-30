# Connecting a Zotero client

This page describes how to connect an **unmodified Zotero Desktop** installation to altero.

**Before you begin:** use a test profile or a library you can recreate.

## Configure Zotero Desktop

Open **Settings → Advanced → Config Editor** and set both preferences:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

The trailing slash on `extensions.zotero.api.url` matters.

For a server behind TLS, use `https://` for the API and `wss://` for streaming.

> [!IMPORTANT]
> `api.url` does not redirect the streaming connection. If `extensions.zotero.streaming.url` is left unchanged, Zotero falls back to its built-in `wss://stream.zotero.org` endpoint and may send the altero API key there. zotero.org rejects that key, but the key may appear in upstream logs.

If you do not want streaming updates, disable streaming explicitly:

```text
extensions.zotero.streaming.enabled = false
```

Restart Zotero after changing the preferences.

## Link the account

In Zotero, open **Settings → Sync → Link Account**.

The client then:

1. asks altero to create a temporary login session;
2. opens altero's browser interface;
3. waits while you sign in and approve the client; and
4. receives an API key for synchronization.

The key can access the personal and group libraries available to that account, as Zotero expects.

Approving the client asks for the password again even if the browser is already signed in. The API key remains valid until it is revoked, so approval requires a fresh proof of identity.

## File syncing

Attachment files are configured separately from library data, in **Settings → Sync → File Syncing**. There, *Zotero* means altero, because `extensions.zotero.api.url` points at it. Group libraries always sync their files through altero; WebDAV cannot carry them.

### Keeping an existing WebDAV server

Leave **Sync attachment files in My Library using WebDAV** unchanged. altero then carries the library data and the WebDAV server keeps carrying the files.

A personal library [migrated from zotero.org](administration.md#move-a-personal-library-from-zoteroorg) keeps its item keys and each attachment's `md5` and `mtime`, so the `<KEY>.zip` and `<KEY>.prop` files already on the WebDAV server still match.

### Moving files from WebDAV into altero

Files stored on WebDAV are never present on zotero.org, so a migration cannot bring them across. Move them from a client whose Zotero data directory still holds them:

1. Set **Settings → Sync → File Syncing → Sync attachment files in My Library using Zotero**.
2. Open **Settings → Sync → Sync Reset → Show Reset Options…**, select the library, and run **Reset File Sync History**.
3. Sync.

Step 2 is required. Zotero otherwise treats the files as already synchronized, because the migrated attachments carry the same `md5` and `mtime` the WebDAV server recorded, and uploads nothing. The reset marks every attachment whose file is present locally for upload.

> [!WARNING]
> This uploads the whole attachment store in one sync. altero accepts up to 1 GB per file; a reverse proxy needs its own request-size limit raised, as described under [Behind a reverse proxy](deployment.md#behind-a-reverse-proxy).

An attachment whose file no longer exists anywhere stays a metadata-only item. altero answers 404 for its bytes, and Zotero records it as in sync rather than reporting an error.

## Command-line approval

If the browser interface is not built, the same login can be approved from the server shell:

```sh
uv run altero login list
uv run altero login approve <token> <username>
```

`login approve` creates a key unless you supply an existing one with `--key`.

## Test with two desktop clients

Two Zotero installations on one machine can use separate profiles and data directories. This is useful for testing whether changes really travel through the server rather than only exercising one side of sync.

See [Syncing two desktop clients](testing-two-clients.md).

## Mobile apps are not supported

altero currently works with Zotero Desktop only.

The official Zotero iOS and Android applications compile `https://api.zotero.org` into the application and expose no runtime setting for another API host. Supporting them would require patched mobile builds, which is outside altero's scope.

For the reasoning and evidence behind that boundary, see [Why altero exists](motivation.md).
