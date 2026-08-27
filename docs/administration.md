# Administration

This page covers operations that affect the altero instance, accounts, groups or complete libraries.

**For ordinary account settings:** see [Web interface](web-interface.md).

## What an instance administrator can do

Most altero permissions belong to a library. The **instance administrator** role is different: it can operate the server itself.

An instance administrator can manage accounts, retention, identity providers and storage information. The role does **not** grant automatic access to other users' library contents. An administrator can count and operate libraries without being allowed to read their items, notes or files.

The first account that claims a fresh instance becomes an administrator. The last administrator cannot demote, suspend or delete themselves, so a working instance cannot be left without one through normal administration.

From the shell:

```sh
uv run altero user admin <username>
uv run altero user admin <username> --revoke
```

## Common command-line tasks

The browser covers most routine administration. The command line remains useful for initial setup and recovery.

### Accounts and credentials

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
```

### Groups

```sh
uv run altero group add <name> --owner <username> [--public]
uv run altero group member <group-id> <username> [--role admin]
uv run altero group members <group-id>
uv run altero group role <group-id> <username> <member|admin>
uv run altero group remove <group-id> <username>
uv run altero group delete <group-id> [--yes]
```

### Libraries and retention

```sh
uv run altero library list
uv run altero library set-version <user|group> <id> <version>
uv run altero library export <user|group> <id> <archive.zip>
uv run altero library import <archive.zip> [--replace]

uv run altero retention show
uv run altero retention run [--dry-run] [--trash DAYS]
```

### Desktop login approval

```sh
uv run altero login list
uv run altero login approve <token> <username> [--key KEY]
```

## Administration screens

The browser shows **Administration** only to an account with the instance-administrator role.

### Overview

The overview reports the altero version, Web API version, database dialect, attachment directory and Alembic revision. It also shows account, library and group counts.

### Storage

Storage reports both:

- **on disk** — the physical bytes the instance stores; and
- **counted across libraries** — the sum each library would account for separately.

The totals differ because altero stores the same attachment content once per digest even if several libraries reference it.

The screen also identifies:

- unreferenced files; and
- attachments whose expected bytes are missing.

Removing unreferenced files is an explicit administrator action, not a timed retention rule. Recent files are left alone because an upload can temporarily exist on disk before the database row that references it is committed.

## Accounts

The Accounts screen can create an account, reset access, suspend it, revoke credentials or delete it.

### Create an account

An administrator can create an account with a username and password. The initial password is shown once and should be handed to the user securely; the user can then change it.

Browser registration is available only when one of these conditions applies:

- this is the first account on a fresh instance;
- `ALTERO_OPEN_REGISTRATION` enables registration; or
- the email address has been invited to a group.

### Password reset

An administrator can either set a password or issue a single-use link that lets the account holder choose a new one.

The link is valid for 12 hours. If the account has a confirmed address and outgoing mail is configured, altero can email it. The administrator is also shown the link so an instance without mail can still recover an account.

Optional self-service password reset is controlled by `ALTERO_PASSWORD_RESET` and requires an SMTP relay.

### Suspend an account

Suspension blocks both forms of access:

- browser sessions; and
- API keys used by Zotero Desktop.

No library data is deleted. Re-enabling the account restores access with the existing credentials unless those credentials were separately revoked.

### Revoke credentials

Credential revocation signs out browser sessions and invalidates API keys without disabling or deleting the account.

This is appropriate for a lost device or leaked credential. The user can continue using the account after creating or receiving new credentials.

### Delete an account

Deleting an account removes its personal library. It is refused while the account owns a group, because altero will not guess who should inherit that group.

Deletion is also refused for your own currently signed-in administrator account and where it would remove the last administrator.

## Sign-in providers

**Administration → Sign-in providers** configures OpenID Connect and SAML 2.0 for browser sign-in.

The Zotero API itself remains API-key based. Institutional sign-in changes how a user reaches the browser session that can issue a key; it does not change the synchronization protocol.

### Before adding a provider

Set `ALTERO_PUBLIC_URL` first. The administration screen shows the redirect/callback address that must be registered with the identity provider.

A callback mismatch is rejected by the provider before altero can complete sign-in.

### OpenID Connect

Store the client credentials and provider settings in the administration screen. Client secrets are write-only: the interface can replace a secret but does not display the existing value.

### SAML 2.0

A SAML provider requires:

- the identity provider entity ID;
- the sign-on URL; and
- one or more signing certificates in PEM form.

Multiple certificates can be stored during signing-key rollover.

The SAML implementation is deliberately limited to:

- SP-initiated sign-in;
- signed, unencrypted assertions; and
- local sign-out only, with no SAML Single Logout.

### Account creation and deprovisioning

Automatic account creation through a provider is **off by default**. Turning it on allows identities accepted by that provider to create local altero accounts.

A provider can also require a claim and value, such as an entitlement or group. On each sign-in, altero checks the requirement. If a previously linked user no longer has the required claim, the local account is suspended, which also stops existing Zotero API keys.

This check happens at sign-in time. It cannot detect a person who leaves the organization and never attempts to sign in again; administrators must handle that case through the Accounts screen or another operational process.

Removing a provider removes the account links to it, not the local accounts themselves.

## Retention

Retention starts conservatively: the default trash-retention period is **never delete automatically**.

Configuration values:

```python
TRASH_RETENTION_DAYS = 0
ACTIVITY_RETENTION_DAYS = 0
UPLOAD_RETENTION_HOURS = 24
RETENTION_INTERVAL = 0
```

`0` means “no automatic retention action” for the day-based settings and interval. Browser-configured values override the configuration file; clearing a browser override returns to the configured value.

Inspect and run retention from the shell:

```sh
uv run altero retention show
uv run altero retention run --dry-run
uv run altero retention run --dry-run --trash 30
uv run altero retention run
```

### Why trash cleanup is a normal delete

When retention removes trashed Zotero objects, the library advances by one version and the deletions are recorded. A client that later asks `/deleted?since=` can therefore learn what disappeared.

Removing database rows without the deletion log would leave offline clients holding objects the server had silently forgotten.

Unreferenced attachment files are not deleted by the timed retention sweep. They are handled separately from the Storage screen to avoid racing uploads that have written their bytes before committing their item rows.

### Rows that carry their own expiry

Browser sessions, sign-in codes, confirmation links, unanswered invitations and attachment download permissions have no retention period of their own. Each records when it expires, and the sweep removes it once it has: an expired session is already nobody's session, and an expired download permission opens nothing.

Download permissions are the highest-volume of these. A client syncing its files is granted one per attachment it fetches, so the sweep is what keeps that table from growing for as long as the instance runs. See [the file protocol](compatibility.md#the-location-has-to-be-a-credential) for what they are and why the redirect cannot simply point at a URL carrying the API key.

## Library transfer and recovery

### Move a library to another altero instance

Export the library:

```sh
uv run altero library export user 1 library.zip
```

On the destination, create the owning account or group first, then import:

```sh
uv run altero user add <username> --id 1
uv run altero library import library.zip
```

The archive contains JSON metadata and attachment bytes, including object keys, object versions, the library version and the deletion log. Accounts and API keys are not included.

Importing into a non-empty target is refused unless `--replace` is used.

The browser exposes equivalent import/export operations under **Settings → Import and export**.

### Move a personal library from zotero.org

If possible, create the altero account with the same numeric user ID that zotero.org uses:

```sh
uv run altero user add <username> --id <zotero.org-user-id>
uv run altero migrate zotero <username> --replace
```

The migration asks for a zotero.org API key with read access to the personal library. The key is prompted for rather than placed on the command line.

The migration preserves Zotero object keys and versions so an already-synchronized desktop client can continue from the same state.

If the local altero user ID differs from the zotero.org user ID, Zotero Desktop can require a reset and re-download because the client remembers which account number last synchronized that data directory.

Only the personal library is imported. Attachment bytes that are not present on zotero.org cannot be downloaded.

### After recreating the database

A newly recreated library begins at a low library version, while existing clients may remember a much higher version. Zotero refuses to move its stored version backwards.

Raise the server library version above the version remembered by the client:

```sh
uv run altero library set-version user 1 100
```

This command only raises versions; lowering a working library version can lock clients out.

Raising the version does not recreate data that was lost with the database. Use Zotero's **Restore to Server** afterwards if you need the client to upload a complete copy.

## Group policy

A group has three Zotero-compatible policy settings:

| Setting | Values | Controls |
| --- | --- | --- |
| `libraryReading` | `members`, `all` | Who may read the library |
| `libraryEditing` | `members`, `admins` | Who may edit objects |
| `fileEditing` | `none`, `members`, `admins` | Who may upload attachment files |

The group `type` is `Private`, `PublicOpen` or `PublicClosed`.

A public group is readable without a key only when the group is public **and** `libraryReading` is `all`.

Membership remains a ceiling over key permissions: a key that grants access to all groups still cannot read a group the account does not belong to.

### Per-member permissions

altero can apply an additional restriction to one member:

| Permission | Meaning |
| --- | --- |
| `inherit` | Use the normal group policy |
| `read` | Read only |
| `add` | Create and change, but do not remove or trash |
| `own` | Create freely; change or remove only items that member added |

From the shell:

```sh
uv run altero group member <group> <username> --permission read
uv run altero group permission <group> <username> add
uv run altero group members <group>
```

These permissions can only restrict what the group policy already allows. They do not elevate a member above the group's normal policy.

Only the read-only state maps cleanly onto a permission the Zotero sync client understands. `add` and `own` are enforced server-side; a client that attempts a forbidden operation receives a sync error explaining the restriction. See [Compatibility notes](compatibility.md#finer-roles-for-one-member).
