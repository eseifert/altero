# Moving, importing and exporting data

Use these features when moving a personal library from zotero.org, backing up a complete altero library, or moving a library between compatible altero instances.

## Common tasks

- Move a personal library from zotero.org from **Settings**.
- Export a complete altero library archive for backup or transfer.
- Import an altero library archive into the selected target library.
- Use ordinary Zotero export formats when you want data for another application rather than a server backup.

## Detailed behavior

The sections below retain the technical and behavioral detail needed for troubleshooting and development. You can stop after the task summary if you only need to use the feature.

### Moving in from zotero.org

Settings offers to copy your personal library out of zotero.org and put it
here: items, collections, tags, saved searches, notes, the trash, the deletion
log and the attachment bytes, at **the versions your clients already know**.
It is not an export and re-import — nothing is renumbered, so the copy is the
library rather than a new library with the same contents in it.

**It takes an API key, not your zotero.org password.** zotero.org has no
password sign-in for other programs; its API accepts a key and nothing else.
So the screen asks you to make one at zotero.org → Settings → Security →
Applications, allow it to read your personal library, and paste it in. The key
is used for that one copy and is never stored, logged or written to the
database.

**It replaces rather than merges.** A library here with anything in it is
refused unless you tick the box, exactly as restoring an archive is: two
libraries sharing one set of keys is not something a client could make sense
of. There is no trash around what it discards.

**Your desktop client will want to reset itself afterwards**, and should be
allowed to. Zotero refuses to sync a library it last synced under a different
account number without erasing its local copy first — `checkUser` in the
client's own sync code — and unless your account here happens to have the same
number as your zotero.org one, that is what it sees. Everything it needs is on
the server by then, so it re-downloads rather than losing anything. An
administrator who wants to avoid even that can create the account with
`altero user add <name> --id <zotero.org user id>` before migrating.

It takes minutes, not moments — thousands of items at a hundred a request, one
download per attachment, at whatever pace zotero.org allows — so the page
starts the work and then reports on it: the stage, the count within it, and at
the end what came across. **The record of a running migration lives in the
server process**, so an instance behind several workers can start one on
one worker and be told "nothing running" by another, and a restart forgets
that a migration happened. What it *did* is in the library either way.

If zotero.org refuses part of the library, the copy goes on without it and
says which part at the end. Its `/tags?format=versions` currently answers 500
for every library, so the tags arrive with the library's version rather than
their own — which nothing you can see depends on. Items, collections and saved
searches are the exception: those *are* the library, and a copy missing them
would not be one, so a failure there stops the migration with nothing written.

What it cannot bring: group libraries (only the personal one), and files
zotero.org has no copy of — a linked file was never uploaded, and a stored one
is only there if the account had the storage. Those attachments arrive as
items without their bytes, and are counted and named at the end rather than
passed over quietly. The same is true of anything this server cannot store: an
item is left behind and named, rather than stopping the rest of the library
getting through.

**Files synchronized over WebDAV are the case where that count is the whole
library.** zotero.org holds no copy of any of them, so every attachment arrives
without its bytes while the migration itself succeeds. The summary says so
where it is read, since the screen is where somebody looks first, and
[Connecting a Zotero client](../clients.md#file-syncing) has both ways on: keep
the WebDAV server for files, or move them into altero from a client that still
has them.

The command line does the same thing, with the archive left on disk:

```sh
uv run altero migrate zotero <username>
```

[compatibility.md](../compatibility.md#reading-a-library-out-of-zoteroorg) covers
what the API cannot serve and what altero does instead.

### Import and export

Settings offers the archive `altero library export` writes, and reads one back.
It is a backup or a move between servers, not an export for another
application: every object at the version clients remember, the deletion log,
and the attachment bytes. The other thing — a bibliography, in any of the
seventeen formats — lives with the items, under
[Writing items out](library.md#writing-items-out).

Both are a link rather than a fetch, so the browser streams the file to disk and
shows its own progress; an archive is as large as the library it came from, and
a library's worth of BibTeX is not something to assemble in memory either.

Restoring is the one place the browser writes to a library, and it writes all of
it, so it is fenced three ways:

- **The session picks the target, not the file.** The library is the one chosen
  on the screen. An archive names a library in its manifest and that name is
  ignored here — an uploaded file naming `user/2` would otherwise be restored
  over user 2's library.
- **Who may.** A personal library is its owner's. For a group, an administrator
  may take a copy, and only the owner may restore over one: that ends the
  library as its members knew it, which is what deleting the group does and is
  held to the same person.
- **The password again, and an explicit replace.** A library that already holds
  anything is left alone rather than merged into, unless "replace what this
  library already holds" is ticked — and then the screen says, before the
  button is pressed, that everything in that library goes, files included.

Both ends are the same `services/transfer.py` the command line uses, so an
archive from either can be read by either.

One thing to know before restoring a *different* library's archive over your
own: the version counter comes from the archive, so it can move backwards, and
a client that synced past that point will not notice what changed underneath
it. `altero library set-version` is the way out; see
[administration.md](../administration.md#after-recreating-the-database).
