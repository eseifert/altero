# Administration

The Web API cannot create accounts or issue credentials. It can administer a
**group** — creating one, changing it, and deciding who belongs to it — with an
ordinary API key, and so can the [web interface](web-interface.md#groups); see
[compatibility.md](compatibility.md#groups) for what that copies from upstream
and what it does not. Accounts, credentials and anything else about another
person are still command-line operations.

```sh
uv run altero user add <username> [--display-name NAME] [--id N]
uv run altero user list
uv run altero user password <username>
uv run altero user admin <username> [--revoke]
uv run altero key add <username> [--name LABEL] [--read-only] [--groups]
uv run altero key list
uv run altero key revoke <key>
uv run altero group add <name> --owner <username> [--public]
uv run altero group member <group-id> <username> [--role admin]
uv run altero group members <group-id>
uv run altero group role <group-id> <username> <member|admin>
uv run altero group remove <group-id> <username>
uv run altero group delete <group-id> [--yes]
uv run altero library list
uv run altero library set-version <user|group> <id> <version>
uv run altero library export <user|group> <id> <archive.zip>
uv run altero library import <archive.zip> [--replace]
uv run altero login list
uv run altero login approve <token> <username> [--key KEY]
```

Registration in the browser opens for three cases: the first account, an
instance whose `ALTERO_OPEN_REGISTRATION` says so, and an address somebody has
invited to a group. Every other account is made here. See
[web-interface.md](web-interface.md#accounts).

The group commands go through the same service the API's group endpoints do, so
the shell and an API key cannot disagree about what a group is or what a role
means. The shell is not a superuser path either: `group delete` removes a
library and everything in it, and asks before it does unless told `--yes`.

## Who administers the instance

Every other permission in altero is per library. This one is not: an
**instance administrator** is the account that may see what the instance costs,
set retention and take an account out of service. It grants nothing over
anybody's library — an administrator counts and measures, and cannot read a
title, a note or a file they were not already entitled to.

The account that claims an instance administers it, whether it was made with
`altero user add` on a fresh database or through the registration form on a
fresh container; both go through the same rule, so an instance cannot end up
with none. On an instance that already existed, the upgrade promotes the
lowest-numbered account, which is the one that claimed it.

```sh
uv run altero user admin grace            # hand the role on
uv run altero user admin ada --revoke     # and stand down
```

The last administrator cannot stand down. An instance with none can only be
given one from a shell on the server, which is what this is for in the first
place.

## Moving a library to another server

```sh
uv run altero library export user 1 library.zip
# on the other instance, where the account must already exist
uv run altero user add <username> --id 1
uv run altero library import library.zip
```

The archive is a ZIP of JSON documents plus the attachment bytes, one copy per
digest. It carries the library's version and every object's, along with the
client timestamps and the deletion log, because a client that synced with the
original remembers all of that: a restore that renumbered versions would look
successful and lock every one of those clients out. `manifest.json` says what
produced it and what it contains.

Accounts and API keys are not in it. An archive is a library, not a user, so
the owning user or group has to exist on the target first — which also means an
archive cannot leak a credential by being copied around. Restoring into a
library that already holds objects is refused rather than merged; `--replace`
discards what is there.

The same two operations are in the browser, under **Settings → Import and
export**, which is what makes a backup something the owner of a library can
take without shell access — see
[web-interface.md](web-interface.md#import-and-export). One difference matters:
the command line restores into the library the manifest names, while the
browser restores into the library you picked there, whatever the file says. A
downloaded archive is an ordinary file that anybody could hand you, and taking
its word for the target would mean an upload could choose somebody else's
library.

## Moving a library in from zotero.org

```sh
# Ideally give the account the number zotero.org knows it by, which is what
# stops the desktop client offering to reset itself afterwards.
uv run altero user add <username> --id <zotero.org user id>
uv run altero migrate zotero <username> --replace
```

It asks for a zotero.org API key — made by its owner at zotero.org → Settings →
Security → Applications, allowed to read the personal library — and prompts for
it rather than taking it as an argument, so it stays out of the shell's history
and the process list. `--server` points it somewhere else, which is how one
altero is read into another; `--archive-only` writes the copy and restores
nothing.

What it does is a download and then the restore above: it writes the same
archive `library export` writes, then hands it to the same import. Keys,
versions and the deletion log come across unchanged, so this is a *move* rather
than a re-entry — a client that had synced with zotero.org is in step with what
lands here.

The account number matters. Zotero refuses to sync a library it last synced
under a different account without erasing its local copy first, so an account
created with `--id` matching the zotero.org one keeps every client working
untouched; without it, each client offers to reset and re-download, which loses
nothing but takes a while. Relations between items are rewritten to the new
number either way.

Only the personal library, and only what zotero.org will serve: an attachment
whose bytes it has no copy of arrives without them, and is counted and named at
the end. The browser has the same thing under **Settings → Move from
zotero.org**; see
[web-interface.md](web-interface.md#moving-in-from-zoteroorg).

## After recreating the database

A library recreated from an empty database counts from zero again, while
clients that synced against the original still hold the version they last saw.
The desktop client refuses to move its stored version backwards, so it can
neither upload — every sync fails with `_libraryStorageVersion cannot decrease`
and retries forever — nor reset itself out of the state, since **Restore to
Server** fails the same way.

Raise the server past what the client remembers, then sync:

```sh
uv run altero library set-version user 1 100
```

The client's own number is in its database, if you want to be exact rather than
generous:

```sh
sqlite3 ~/Zotero/zotero.sqlite \
    'SELECT version, storageVersion FROM libraries WHERE libraryID=1'
```

A version can only be raised, because lowering one is how a working deployment
locks its clients out. Note that objects the client already considers synced
are not re-uploaded, so anything written before the database was recreated
stays missing; use **Restore to Server** afterwards to force a full upload.

## Group policy

A group carries three settings that decide what its members may do, and all
three are enforced rather than merely stored:

| Setting | Values | Effect |
| --- | --- | --- |
| `libraryReading` | `members`, `all` | `all`, on a public group, makes the library readable without a credential |
| `libraryEditing` | `members`, `admins` | who may write items, collections and searches |
| `fileEditing` | `none`, `members`, `admins` | who may upload attachment files, which is where the disk goes |

`type` is `Private`, `PublicOpen` or `PublicClosed`. A group is only readable
without a key when it is public **and** `libraryReading` is `all`: public as a
page is not public as a library, and it is the library this server serves.

Membership is a ceiling over all of it. A key granting "all groups" means every
group its owner belongs to, and a group nobody has added you to is not readable
whatever your key says.

## What has no home yet

An operator's view of the instance — versions, storage use, backups — is not
built. Permissions are per library, and there is no notion of an instance
administrator to show such a view to. Until that exists, an instance is
something a systems administrator runs rather than a librarian or a
research-group lead; [motivation.md](motivation.md) treats that as a gap
against the project's goals rather than a detail.
