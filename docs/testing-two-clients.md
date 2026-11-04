# Syncing two desktop clients

This is the strongest manual test of altero synchronization: two real Zotero Desktop installations use the same library through the server and are compared afterwards.

For automated checks of desktop decisions and source expectations, see
[Desktop compatibility checks](client-compatibility.md).

**Use disposable data:** a failed run should be thrown away, not repaired in place.

## What this test proves

A single client can show that requests succeed. Two clients can show whether changes actually travel through the server and converge on the same state.

The test is useful for:

- conflict handling;
- deletions and trash;
- collection movement;
- attachment changes;
- group libraries; and
- changes made while one client is offline.

## Test setup

Use:

- a dedicated altero instance;
- one test account;
- two separate Zotero profiles/data directories; and
- the same API and streaming endpoints in both profiles.

The two clients should represent two installations of the **same account**, not two unrelated personal libraries.

For a test on Windows or macOS, use two computers or create test profiles using
[Zotero's profile instructions](https://www.zotero.org/support/kb/multiple_profiles).
Before linking either profile, verify that its data directory is empty and
different from your everyday library and the other test profile. Check the
directory in **Settings → Advanced → Files and Folders**. You can run the two
profiles one at a time; [simultaneous instances](https://www.zotero.org/support/kb/multiple_instances)
also require separate profile and data directories.

## Configure both clients

Each Zotero profile needs:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

Restart Zotero and link the same altero account in both profiles.

For a remote server, replace `localhost:8000` with the server's public address
and use `https://` and `wss://` together. Set attachment syncing to **Zotero**
and file downloads to **at sync time** on both clients, so this test exercises
altero's file store.

For the complete linking flow, see [Connecting a Zotero client](clients.md).

## Important traps

### Account ID must match the data directory

Zotero remembers the numeric user ID that last synchronized a data directory. Pointing an existing data directory at a different user ID can trigger Zotero's reset-data-directory protection.

For tests, start with fresh profiles unless you are deliberately testing migration behavior.

### Use separate data directories

Two profiles that share the same Zotero database are not two clients. Each test client needs its own data directory.

### Do not leave streaming pointed at zotero.org

Set `extensions.zotero.streaming.url` on both clients, or disable streaming. The API URL alone does not replace Zotero's built-in streaming endpoint.

### Let each side finish syncing

Do not compare the clients while one still has queued changes or an unresolved sync error.

### Compare server state as well as the UI

A library can look similar in the UI while versions, deleted objects or attachment metadata differ. Use the project comparison tooling after the interactive part of the test.

## Suggested test sequence

Start with a small library and exercise operations that require both directions of sync.

1. Create several item types on client A and sync.
2. Confirm they appear on client B.
3. Add collections, tags, notes and attachments on B and sync back to A.
4. Edit the same item on both clients while one is offline, then reconnect it.
5. Move items between collections.
6. Trash and restore items.
7. Delete an object and confirm the other client learns the deletion.
8. Change an attachment and verify the file reaches the other client.
9. Exercise a group library if the test instance has one.
10. Repeat a sync with no changes and confirm the library does not advance unnecessarily.

The important result is **convergence**: after all syncs finish, both clients and the server agree on the library state.

## Compare the libraries

The repository includes a comparison tool for two local Zotero data directories against the server:

```sh
uv run python tools/compare_libraries.py --key <api-key> \
  A=~/zotero-test/A/data \
  B=~/zotero-test/B/data
```

Use it after the clients report that synchronization is complete.

A passing test should not require manual database repair, object-version changes or a reset of either client.

## Testing group libraries

One account on both clients is still useful for group-library sync because it tests two installations of the same member.

Use additional accounts only when you are specifically testing group membership, permissions, ownership or per-member restrictions.

## Record enough information to reproduce failures

When a run fails, record:

- Zotero version;
- operating system;
- altero revision/version;
- SQLite or PostgreSQL;
- deployment method;
- the exact operation being synced;
- which client made each change;
- the error shown by Zotero; and
- server logs that do not contain private library data or API keys.

## When the run is complete

Discard the disposable instance and test profiles unless they are needed for a minimal reproduction.

A clean two-client run is stronger evidence than replaying captured HTTP traffic because it exercises the real client's local synchronization state in both directions.

The [automated acceptance runner](client-compatibility.md#run-two-real-desktop-profiles)
creates disposable profiles and checks disjoint offline edits, file bytes,
trash/restore, child deletion and schema serialization using the real sync engine.
Keep this manual procedure for same-field conflict dialogs and group-removal
prompts on other platforms too; the automated runner already drives those
dialogs on Linux.

## Windows and macOS reports

Windows and macOS have not completed the project's automated desktop acceptance
suite. A [basic-sync report](https://github.com/eseifert/altero/issues/49#issuecomment-6555801282)
for Zotero 10.0.7 and altero beta.7 is encouraging, but does not cover the checks
below. A manual run records evidence for its checked operations; it does not
certify the full automated matrix.

Use the setup and sequence above, then record **pass**, **fail** or **not run**
for each case. Sync both clients until idle after each change, and check the
browser library as a third view of the server's metadata.

| Check | Operation and expected result |
|---|---|
| Linking and restart | Link each fresh profile, restart it, and sync again without another approval or error. |
| Metadata both ways | Create a book with a creator, Unicode title and tag on A. On B, change its title and add a child note. All three views agree. |
| Collection graph | Create nested collections, file the book, then move a collection on B. The hierarchy and memberships agree. |
| Disjoint offline edits | Disable automatic sync on both. Change the title on A and the date on B; sync A, B, A. Both changes survive. |
| Conflict dialog | With automatic sync off, change the same title differently on both. Sync A, then B, choose a side in the dialog, then sync A. Repeat choosing the other side. All views agree with each choice. |
| Trash and deletion | Trash the book, restore it, then trash and permanently delete it. Sync between steps. Both clients and the browser show each transition and remove its children at deletion. |
| Stored files | Attach a small PDF and a file with a Unicode filename on A. On B, open the downloaded files and compare their actual bytes with the originals. Repeat from B to A. |
| File replacement | Change a stored file on B, sync B then A, and verify A's bytes. Restart both clients and verify the files still open. |
| Browser edits | Edit a field and child note and upload a file through the browser. Both clients receive the edits and matching file bytes. |
| Live updates | Re-enable automatic sync and restart both. Leave B idle; change and sync A. B receives the change without pressing Sync. Record separately if only manual sync works. |
| Groups | If available, repeat metadata and file checks in a group. With a second, read-only member, confirm reading works and editing is unavailable. Otherwise mark this not run. |
| Settled sync | Sync both twice without further edits. No recurring error, conflict or repeated upload appears. |

Report results in [issue #49](https://github.com/eseifert/altero/issues/49),
including successful runs. Copy this outline and fill in every row above:

```text
Date:
Client A: OS version / architecture / exact Zotero version:
Client B: OS version / architecture / exact Zotero version:
altero version or commit:
Database: SQLite / PostgreSQL version:
Deployment: Docker / Podman / source; reverse proxy and TLS setup:
Test profiles with separate, empty data directories: yes / no
Results: check name — pass / fail / not run; observations
Failure: steps, expected result, actual result, and exact error
Recovery required: none / describe
```

Record the first failing step before trying recovery. Keep the disposable state
for a reproduction. Share only logs and screenshots you have checked for API
keys, session tokens, authorization headers, passwords and private library data.
