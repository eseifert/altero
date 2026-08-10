# Syncing two desktop clients

[motivation.md](motivation.md) puts this first among the things that would count
as success: *a real library syncs in both directions between two unmodified
desktop clients through altero, with no divergence and no manual repair.* It is
the one criterion the test suite cannot reach.
`tests/test_sync_cycle.py` drives a real server over a real socket with a
request sequence captured from the client's debug log, which is a replay; two
installed clients disagreeing about a library is a thing only two installed
clients can show.

Both of them fit on one machine. What follows is the rig, the four traps in it,
and the tool that decides whether the run passed.

## The rig

An instance of its own, so that a failed run is thrown away rather than
repaired. Every command below carries the same two variables; the server needs
them too.

```sh
export ALTERO_DATABASE_URL=sqlite+aiosqlite:///$HOME/zotero-test/altero.sqlite
export ALTERO_STORAGE_PATH=$HOME/zotero-test/storage
mkdir -p ~/zotero-test/{A,B}/profile

uv run altero user add <username> --id <user id>   # see "The account id" below
uv run altero                                      # :8000
```

Two client installations are two profiles with two data directories. Both are
command-line arguments, and they behave differently: `--profile` is Gecko's and
takes a directory that **must already exist** — a missing one is answered with
"Your Zotero profile cannot be loaded. It may be missing or inaccessible.",
which is why the `mkdir` above creates them — while `-datadir` is Zotero's own
(`BrowserContentHandler.sys.mjs`), takes an absolute path whose *parent* exists,
and creates the directory itself.

Seed A before its first launch, with a copy of a real library taken while the
installation that owns it is closed. Zotero initialises an empty library in a
data directory it finds empty, and copying over that afterwards means copying
over a database in use:

```sh
cp -a ~/Zotero/. ~/zotero-test/A/data/
```

Then start them. `--new-instance` is what lets the second one run while the
first is up:

```sh
zotero --profile ~/zotero-test/A/profile -datadir ~/zotero-test/A/data --new-instance &
zotero --profile ~/zotero-test/B/profile -datadir ~/zotero-test/B/data --new-instance &
```

Each profile needs `extensions.zotero.api.url` and
`extensions.zotero.streaming.url`, as [clients.md](clients.md) describes — the
streaming URL is not derived from the API one, and left alone the client sends
your key to zotero.org. **Settings → Advanced → Config Editor** sets them, but a
`user.js` in the profile directory keeps the rig out of the GUI and survives
every restart:

```sh
for p in A B; do cat > ~/zotero-test/$p/profile/user.js <<'PREFS'
user_pref("extensions.zotero.api.url", "http://localhost:8000/");
user_pref("extensions.zotero.streaming.url", "ws://localhost:8000/stream");
PREFS
done
```

`user.js` is applied at every startup, so it also overrides anything the Config
Editor is later used to change. Then **Settings → Sync → Link Account** in both
— `altero login approve` completes it from the command line — and turn on file
syncing for My Library and for group libraries, or attachments will never be
part of what is being tested.

Finally, in A alone, and only if it is seeded from a library this server has
never held: **Settings → Sync → Reset → Restore to Online Library**. Leave the
installation you copied from pointed where it was.

## The four traps

**The account id.** If the data directory last synced as a different `userID`,
the client offers to delete the whole data directory rather than sync it
(`checkUser` in `xpcom/sync/syncLocal.js` writes a `reset-data-directory` marker
and quits). Read the id out of the library you are copying and give it to
`altero user add --id`:

```sh
sqlite3 "file:$HOME/Zotero/zotero.sqlite?immutable=1" \
    "select key, value from settings where setting = 'account';"
```

**The version the copy remembers.** A copied library remembers the version it
reached on zotero.org — several hundred — and a new altero library is at 0. A
client that remembers a higher version than the server reports is the state
`altero library set-version` exists for, but do not start there: **Restore to
Online Library** resets every local object to version 0, marks the library
unsynced and uploads it whole (`_restoreToServer` in `xpcom/sync/syncEngine.js`),
which is both the seeding step and the answer to this.

**Groups do not follow the copy.** A group in the copied library exists under
its zotero.org id, and this server has never heard of it. Create the group here
first if it is part of what you want tested; `altero group add` assigns the id
itself, so check what it got. A group is also the only way to exercise the
Zotero 9 group-level file-naming setting, which nothing here has yet confirmed
against a real 9.0 client.

**The clients must be closed before comparing.** The comparison reads
`zotero.sqlite` directly and opens it read-only, which SQLite refuses on a
database with a hot journal rather than handing back half a transaction. Quit
both.

## Deciding whether it passed

```sh
uv run python tools/compare_libraries.py --key <api key> \
    A=~/zotero-test/A/data \
    B=~/zotero-test/B/data \
    server=http://localhost:8000
```

It reads each client's database and the server's v3 API, reduces all three to
one shape and prints every object they disagree about, field by field. It exits
non-zero when they do. `--library group/<id>` compares a group instead of
`user/1`; `--ignore-versions` compares the data alone, for the case where one
client is legitimately behind.

The server is read as a third source on purpose. Two clients agreeing proves
less than it looks: they could agree on something the server mangled, each
holding its own cached copy of what it sent.

Both readers end in the same canonicalisation, and
`tests/test_compare_libraries.py` is what holds them to it — it builds a client
database and the API's answer for the same library and fails if they reduce to
different things. Without that the tool would report divergence that is really
two ways of writing an item down.

What it does not check: the bytes in `storage`. It compares the `md5` and
`mtime` each client recorded for an attachment, which is what the sync protocol
carries, not the files themselves. `mtime` is compared as a number on both
sides rather than as it arrives, because the client stores an integer and
altero serves a JSON string.

## What to put through it

Everything in this list has a way of going wrong that a single client never
shows.

- Edit the same item on both clients while one is offline, then bring it back.
- Delete an item on one and edit it on the other.
- Move items between collections; move a collection under another.
- Rename a tag, which rewrites every item carrying it.
- Add a PDF, let it index, annotate it, and check the annotation arrives.
- Trash something on one client, restore it on the other, empty the trash.
- Publish an item to My Publications and change its licence.
- Do all of it again in a group library, with the second client as a member.

An external annotation — one that lives in the PDF rather than in the library —
is deliberately not counted: the client never uploads it
(`getUnsynced` in `xpcom/sync/syncLocal.js` excludes it by name), so a server
without it is not behind.

## When it is over

`motivation.md` says point 1 is not evidenced by the thing it describes. If a
run of this comes out clean, that paragraph is what changes, and it should say
what was synced and between which versions rather than that syncing works.
