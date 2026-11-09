# Connecting a Zotero client

This page describes how to connect an **unmodified Zotero Desktop** installation to altero.

Automated desktop acceptance has run on Linux. Windows and macOS have a
community basic-sync report, with broader coverage still unverified; see
[platform status](status.md) and [testing instructions](testing-two-clients.md#windows-and-macos-reports).

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

Use the browser window Zotero opens to sign in and approve the connection.
Zotero receives an API key that covers the account's personal and group libraries.

Approval requires fresh identity confirmation. Enter your password when asked,
or use **Confirm with &lt;provider&gt;** for a provider-linked account without a
password. Complete the approval within five minutes of provider confirmation.
On an institutional-only instance, confirmation always uses the provider.

### A profile that has synced before

Zotero remembers the numeric account id its data directory last synced under, and sends it when linking. altero refuses to hand a key to a different account, because the desktop client reacts to a changed id by offering to reset the data directory and quitting.

If the remembered account number differs from your altero account number, linking is refused and the message names the expected number.

To continue:

- **Create the account with that id.** `altero user add <username> --id <id>` gives the profile the account it is asking for, and it carries on. This is also what [moving a personal library from zotero.org](administration.md#move-a-personal-library-from-zoteroorg) relies on.
- **Link from a data directory that has never synced.** A fresh Zotero profile sends no id. Nothing is carried over by doing this; the old library stays where it is.

## File syncing

Attachment files are configured separately from library data, in **Settings → Sync → File Syncing**. There, *Zotero* means altero, because `extensions.zotero.api.url` points at it. Group libraries always sync their files through altero; WebDAV cannot carry them.

### Keeping an existing WebDAV server

Leave **Sync attachment files in My Library using WebDAV** unchanged. altero then carries the library data and the WebDAV server keeps carrying the files.

A personal library [migrated from zotero.org](administration.md#move-a-personal-library-from-zoteroorg) keeps its item keys and each attachment's `md5` and `mtime`, so the `<KEY>.zip` and `<KEY>.prop` files already on the WebDAV server still match.

### Moving files from WebDAV into altero

Files stored on WebDAV are never present on zotero.org, so a migration cannot bring them across. Move them from a client whose Zotero data directory still holds them:

> [!WARNING]
> This uploads the whole attachment store in one sync. altero accepts up to 1 GiB per file by default ([`ALTERO_MAX_UPLOAD_MB`](configuration.md#server-and-storage)); a reverse proxy needs its own request-size limit raised, as described under [Behind a reverse proxy](deployment.md#behind-a-reverse-proxy).

1. Set **Settings → Sync → File Syncing → Sync attachment files in My Library using Zotero**.
2. Open **Settings → Sync → Sync Reset → Show Reset Options…**, select the library, and run **Reset File Sync History**.
3. Sync.

Step 2 is required. Zotero otherwise treats the files as already synchronized, because the migrated attachments carry the same `md5` and `mtime` the WebDAV server recorded, and uploads nothing. The reset marks every attachment whose file is present locally for upload.

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

## Mobile apps

The official iOS and Android apps have no setting for a different server.
They need a separate build that sends both API and streaming traffic to altero;
altero does not distribute one.

For Android, the third-party
[zotero-self-hosted-sync](https://github.com/raphaelbahat/zotero-self-hosted-sync)
patch bundle can change those addresses. Check its README for supported app
releases. It is not maintained or reviewed by altero and will hold your API key.

| App | Evidence |
| --- | --- |
| Android | Sync and file uploads reported working on a device with a redirected build |
| iOS | Checked against source; no device test recorded |

This route is unofficial, but protocol differences from zotero.org are worth
[reporting](https://github.com/eseifert/altero/issues). Sign-in uses browser
approval as on the desktop.
