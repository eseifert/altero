# Syncing two desktop clients

This is the strongest manual test of altero synchronization: two real Zotero Desktop installations use the same library through the server and are compared afterwards.

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

## Configure both clients

Each Zotero profile needs:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

Restart Zotero and link the same altero account in both profiles.

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
