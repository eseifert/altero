# Moving, importing and exporting data

Choose the tool that matches your goal:

| Goal | Tool |
| --- | --- |
| Move your personal library from zotero.org | **Settings → Import and export**, migration from zotero.org |
| Back up a library or move it between altero instances | An altero library archive |
| Use references in another application | **Export…** in the library view |

## Moving in from zotero.org

This is a one-time copy, not continuing synchronization between servers.

1. Finish syncing to zotero.org, back up your library and pause edits.
2. In zotero.org's account settings, create an API key with read access to your personal library.
3. Open altero's migration screen under **Settings → Import and export** and enter that key. Your zotero.org password is not needed.
4. Review the target library. Migration replaces its contents only if you explicitly allow replacement; it does not merge libraries.
5. Start the copy, wait for completion, and review the summary for skipped items or missing files.
6. Follow [Connecting a Zotero client](../clients.md) before switching the desktop application.

The copy preserves object identifiers and sync versions. The temporary
zotero.org key is used for the copy and is not stored. Group libraries are
not imported.

> [!IMPORTANT]
> A Zotero profile that has synced before remembers its account number. Linking to a different account is refused. Ask the administrator about preserving the original account number, or use a fresh profile; see [A profile that has synced before](../clients.md#a-profile-that-has-synced-before).

Only files present on zotero.org can be copied. Linked files, files not
uploaded there, and WebDAV files are absent. Keep a client or backup that
holds them. For WebDAV, you can keep the existing file server or
[upload the local files to altero](../clients.md#moving-files-from-webdav-into-altero).

Use a single server process for browser migration and avoid restarting it
while the copy runs. Check the result before reconnecting clients.
For shell migration, see [Administration](../administration.md#move-a-personal-library-from-zoteroorg).

## Import and export

An altero archive contains a complete library's objects, sync history and
stored attachment bytes. Accounts, API keys and instance configuration are
not included. For a complete server backup, follow [Backups](../deployment.md#backups).

Under **Settings → Import and export**, choose a library and export its archive.
For a group, an administrator may export; only its owner may restore.

To restore, select the target library and an archive. Confirm your identity
when asked. A non-empty library is left unchanged unless you explicitly enable
replacement.

> [!WARNING]
> Replacement discards the target library's existing contents, including files. Keep a backup and pause client edits first. Restoring an older archive does not automatically rewind already-synchronized desktop copies. Follow the [recovery procedure](../administration.md#after-recreating-the-database) before resuming sync.

## Export references for another application

Use **Export…** above the item list or in the detail or selection pane. Choose
which references to include and a format such as BibTeX, RIS, CSV or CSL JSON.
An export follows the selected view or search past the end of the loaded page.

Reference exports do not include attachment bytes or a complete sync history
and are unsuitable as server backups. See [Writing items out](library.md#writing-items-out).
