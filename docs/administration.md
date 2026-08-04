# Administration

The Web API cannot create accounts or issue credentials, and the [web
interface](web-interface.md) can only administer the account you are signed in
as. Everything about somebody else is a command-line operation.

```sh
uv run altero user add <username> [--display-name NAME] [--id N]
uv run altero user list
uv run altero user password <username>
uv run altero key add <username> [--name LABEL] [--read-only] [--groups]
uv run altero key list
uv run altero key revoke <key>
uv run altero group add <name> --owner <username> [--public]
uv run altero group member <group-id> <username> [--role admin]
uv run altero library list
uv run altero library set-version <user|group> <id> <version>
uv run altero library export <user|group> <id> <archive.zip>
uv run altero library import <archive.zip> [--replace]
uv run altero login list
uv run altero login approve <token> <username> [--key KEY]
```

Registration in the browser is open only while the instance has no users at
all, so a fresh container is reachable without shell access and closes itself
the moment that account exists. Every account after the first is made here.

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

## What has no home yet

An operator's view of the instance — versions, storage use, backups — is not
built. Permissions are per library, and there is no notion of an instance
administrator to show such a view to. Until that exists, an instance is
something a systems administrator runs rather than a librarian or a
research-group lead; [motivation.md](motivation.md) treats that as a gap
against the project's goals rather than a detail.
