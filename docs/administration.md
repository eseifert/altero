# Administration

The Web API cannot create accounts or issue credentials. It can administer a
**group** — creating one, changing it, and deciding who belongs to it — with an
ordinary API key, and so can the [web interface](web-interface.md#groups); see
[compatibility.md](compatibility.md#groups) for what that copies from upstream
and what it does not.

Everything else about another person — making them an account, resetting their
password, suspending them, deleting one — is an *instance administrator's*
work, and is done either here or in the browser under **Administration**. The
two go through the same service, so the shell and the screen cannot disagree
about what any of it means.

```sh
uv run altero user add <username> [--display-name NAME] [--id N]
uv run altero user list
uv run altero user password <username>
uv run altero user admin <username> [--revoke]
uv run altero user disable <username> [--undo]
uv run altero user revoke <username>
uv run altero user delete <username> [--yes]
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
uv run altero retention show
uv run altero retention run [--dry-run] [--trash DAYS]
uv run altero login list
uv run altero login approve <token> <username> [--key KEY]
```

Registration in the browser opens for three cases: the first account, an
instance whose `ALTERO_OPEN_REGISTRATION` says so, and an address somebody has
invited to a group. Every other account is made by an administrator, here or on
the **Accounts** screen. See [web-interface.md](web-interface.md#accounts).

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

### What the operator's screens show

Under **Administration** in the browser, next to Settings and only for an
account that has the role.

**Overview** is what the instance is running — altero's version, the Web API
version, the database's dialect, the directory the attachments are in, and the
Alembic revision the database is stamped with, which is the question an upgrade
asks and otherwise means a shell and `alembic current`. Below that, how many
accounts, libraries and groups there are, and what is on disk.

**Storage** is what each library costs, and it reports two totals rather than
one. Files are stored once per digest, so a paper attached in a group and in
somebody's own library is on disk once and in both libraries' accounts. *On
disk* is what this server has to hold; *counted across libraries* is what the
libraries would cost apart, and the difference is what storing each file once
has saved. zotero.org cannot tell those apart — group files bill to the owner's
quota — which is what the storage threads on the forums are about.

Two things that do not add up are reported alongside: files nothing references
any more, which is where a self-hosted instance quietly loses disk, and
attachments whose bytes are not there, which is what a restore that lost its
files looks like.

The first can be deleted, and it is the only thing on these screens that
removes bytes — a button, never a timer, asking for your password. A file
reaches the disk before the item row that refers to it is committed, so an
upload in flight is indistinguishable from an orphan; anything written in the
last day is left where it is for that reason. Nothing else here deletes.

The numbers are counted when the screen is opened rather than kept in a
counter, because a counter maintained on every upload can drift from the disk
it describes — which is the failure this is meant to catch.

### Accounts

**Accounts** lists everybody with an account here — whether they administer the
instance, whether they are suspended, how many API keys they hold and how many
groups they are in — and does the four things below, each of which the command
line does too.

**Making one** takes a username and a password, which is shown once and never
again, exactly as `altero key add` shows a key once; handing it over is your
business, and the person changes it in their own settings. An address is
optional, as it is for `altero user add`.

**Setting somebody's password** ends their other browser sessions and tells them
about it, if they have a confirmed address — the same `altero user password`
does. The better of the two ways is next to it: **Send a password link** issues
a single-use link, good for twelve hours, that the account sets its *own*
password from, so the password is not known to two people. It is emailed where
there is a confirmed address and shown to you either way, because most
instances have no relay configured and a link readable only in the log would
need the shell this screen replaces.

**A forgotten password** is the account's own affair where the instance allows
it. `ALTERO_PASSWORD_RESET` opens a form on the sign-in page that mails the
same single-use link, and it is off by default because it makes the relay part
of the authentication: whoever can read the mailbox can take the account. It
does nothing without `ALTERO_SMTP_URL` — a self-service link written to the log
is one anybody who can read the log can follow — and nothing for an account
whose address was never confirmed, since nobody has proved they hold it. The
form answers the same way whatever it finds, so it cannot be used to ask which
addresses have accounts here, and one address may ask three times an hour. On
an instance that leaves it closed, the link above is the answer to a forgotten
password.

**Suspending** stops *both* credentials: the API key a Zotero client holds and
this interface. That is the whole of it — a suspension the browser honoured
alone would leave every sync client of that account working exactly as before.
Nothing they own is touched, and reinstating them puts everything back, which is
what makes this the answer to somebody leaving while their library is still
wanted.

**Deleting** removes the account, its personal library and everything in it,
through the same machinery that deletes a group. It is refused while the account
owns a group — the groups are named, and handing one on is its own operation
rather than something this should guess at — and refused for your own account.
Attachment bytes are shared by digest and stay: another library may have
uploaded the same file.

The last administrator cannot be suspended, demoted or deleted, and every one of
these asks you to prove the browser is yours before it does anything, as your
own settings do for anything touching a credential. Your own password is the
usual proof, and it stands for five minutes once given, so a run of account
operations is one prompt rather than one each.

## Sign-in providers

**Administration → Sign-in providers** configures the directories this instance
accepts a sign-in from. Both OpenID Connect and SAML 2.0 are implemented, and
the screen offers one button per protocol because the fields behind them are
different.

A SAML provider takes three things: its **entity ID**, which is what its
assertions carry as `Issuer`; its **sign-on URL**; and its **signing
certificate** in PEM. Paste both certificates while a directory is rolling its
key over — an instance that could hold only one would go down in the middle of
it. This server's own entity ID is its public URL, so there is nothing further
to invent.

Three things about the SAML implementation are worth knowing, and each is a
deliberate limit rather than an omission. It is **SP-initiated only**: a sign-in
has to start here, because an unsolicited assertion has no request of ours to
match and accepting one means accepting anything the directory's key ever
signed, for any service, at any time — there is no "launch from the portal"
button. **Assertions are not decrypted**: TLS covers the transport and a
decryption key is one more thing to hold. And there is **no Single Logout**:
altero's session is its own, and signing out here signs out here.

Four things are worth knowing before setting one up.

**The callback address has to match.** The screen shows the one to register at
the directory — the OIDC redirect URI, or the SAML assertion consumer service —
and it is built from `ALTERO_PUBLIC_URL`. Where that is unset it
comes from whatever request arrived, which behind a proxy is the proxy's idea
of it — and a redirect URI that does not match is refused by the directory
outright, with an error page nobody here can act on. The screen says so when
the variable is missing. Set it first.

**The client secret is write-only.** It is stored as given and never returned:
a signed-in browser tab is not a way of reading back a credential this instance
holds for somebody else's directory. The form shows whether one is set and
takes a replacement; saving without touching it keeps what is there. A SAML
signing certificate is *not* treated that way and is shown back, because it is
published in the directory's own metadata for anybody to read.

**Making accounts is off by default.** Turning it on means everybody in the
directory may have a library here, which is a policy rather than a detail. With
it off, somebody whose subject nobody has connected is refused and told to sign
in with a password and connect it themselves.

**The required claim is the deprovisioning half**, and it is honest about what
it is. Name a claim and a value — a group, an entitlement — and every sign-in
through that provider checks it. Somebody who no longer carries it is not
merely refused: the account is **suspended**, which stops *both* credentials,
so the API key their desktop client is still syncing with stops working too.
Nothing is deleted, and reinstating them is clearing the flag under
**Accounts**. Optionally the keys are revoked as well, which is the stronger
thing to do when a laptop is not coming back; leaving them is what makes
reinstating somebody restore their sync rather than make them set every client
up again.

What that check **cannot** do is notice somebody who has left and simply stops
signing in — the check only runs when they do. It catches the person who
changed departments and still uses this server, not the person who left the
organisation entirely. For that, **Accounts** lists everybody and suspends in
one click, and that is the honest answer rather than an automatic one this
server is not in a position to give.

Removing a provider removes every account's connection to it. The accounts
stay; somebody whose only way in was that provider is left unable to sign in,
which is why the screen says so.

## Retention

zotero.org empties the trash after 30 days. Here that period is the operator's
own, and it starts at **never**: an instance that began deleting somebody's
trash because it was upgraded would be the worst kind of surprise. **Retention**
under Administration sets three periods, and so does the configuration —

```python
TRASH_RETENTION_DAYS = 0  # 30 matches zotero.org
ACTIVITY_RETENTION_DAYS = 0  # delivered group activity
UPLOAD_RETENTION_HOURS = 24  # uploads whose bytes never arrived
RETENTION_INTERVAL = 0  # seconds; zero means only `retention run` does it
```

— with one rule between them: a value set in the browser wins, and clearing it
returns the setting to the configured one. So an operator who keeps everything
in `config.py` keeps working and sees their own numbers on the screen.

```sh
uv run altero retention show
uv run altero retention run --dry-run            # say what would go
uv run altero retention run --dry-run --trash 30 # …with a period not yet set
uv run altero retention run
```

Two things about the trash sweep matter more than the period.

**It is an ordinary delete.** The library takes one new version, however many
items go, and each deletion is recorded, so the next `/deleted?since=` tells
every syncing client exactly what went. A server that removed the rows quietly
would leave every client holding items that no longer exist, with no way to
find out short of a full re-download.

**Age is measured from `serverDateModified`**, because nothing records when an
item was put in the trash and a column added now would be empty for everything
already in there. The server's own timestamp says the item changed no later
than that, so an item touched while in the trash gets a fresh lease: the sweep
deletes late rather than early, which is the right direction to be wrong in.

Alongside those, and needing no setting, the sweep clears rows that are already
past their own expiry: signed-out browser sessions, confirmation links, and
invitations that expired without ever being answered — an accepted or declined
one is kept, so that re-inviting somebody who said no stays a visible act.

Files that no library references are **not** touched by any of this. Deleting
them is a button on the Storage screen, deliberately not a period: bytes are
written to disk before the item row that refers to them is committed, so a
sweep that deleted unreferenced files would race every upload in flight.

The sweep is safe to run while the server is serving, and safe to run twice at
once: each library is locked while it is swept, and deleting an item that has
already gone is not an error.

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

### One member at a time

The three settings above are the group's answer for everybody in it, which is
all Zotero has. Beside them, each membership carries a **permission** of its
own:

| Permission | What the member may do |
| --- | --- |
| `inherit` | whatever the group's policy allows. The default, and what every membership meant before this existed |
| `read` | read, and nothing else |
| `add` | create and change anything; remove nothing — no trashing, no deleting, no emptying the trash |
| `own` | create freely, and change or remove only the items they added. Collections and saved searches are read-only |

From a shell:

```sh
uv run altero group member <group> <username> --permission read
uv run altero group permission <group> <username> add
uv run altero group members <group>          # id, name, role, permission
```

A permission is a fourth ceiling, applied after the other three: it never lets
somebody past what the group's policy already allows, and it cannot be set on
an administrator, who could lift it in a click. Only `read` can be expressed to
a sync client; `add` and `own` are enforcement only and a client that tries
anyway is refused with a sentence saying why. See
[compatibility.md](compatibility.md#finer-roles-for-one-member) before setting
either, since that refusal is what the member will see.

## What has no home yet

An operator's view of the instance — versions, storage use, backups — is not
built. Permissions are per library, and there is no notion of an instance
administrator to show such a view to. Until that exists, an instance is
something a systems administrator runs rather than a librarian or a
research-group lead; [motivation.md](motivation.md) treats that as a gap
against the project's goals rather than a detail.
