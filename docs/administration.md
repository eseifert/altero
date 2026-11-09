# Administration

This page covers operations that affect the altero instance, accounts, groups or complete libraries.

For your own password, sign-in methods and preferences, use [Accounts and personal settings](web/account.md).

## What an instance administrator can do

Most altero permissions belong to a library. The **instance administrator** role is different: it can operate the server itself.

An instance administrator can manage accounts, retention, identity providers, registered applications and storage information. The role does **not** grant automatic access to other users' library contents. An administrator can count and operate libraries without being allowed to read their items, notes or files.

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

uv run altero oauth add <client-id> --redirect-uri URL [--scope SCOPE] [--confidential]
uv run altero oauth list
uv run altero oauth disable <client-id>
uv run altero oauth rotate-key
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

An attachment can be missing its bytes because they were never here, because they were swept, or because the server removed a stored file that did not match what was uploaded. In each case the client offers the file again on its next sync.

Removing unreferenced files is an explicit administrator action, not a timed retention rule. Recent files are left alone because an upload can temporarily exist on disk before the database row that references it is committed. The same action removes files a write into the store never finished, under the same grace period.

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

Optional self-service password reset is controlled by `ALTERO_PASSWORD_RESET` and requires an SMTP relay and `ALTERO_PUBLIC_URL`.

### Suspend an account

Suspension blocks every form of access:

- browser sessions;
- API keys used by Zotero Desktop; and
- OAuth access tokens held by connected applications.

No library data is deleted. Re-enabling the account restores access with the existing credentials unless those credentials were separately revoked.

### Revoke credentials

Credential revocation signs out browser sessions and invalidates API keys without disabling or deleting the account.

This is appropriate for a lost device or leaked credential. The user can continue using the account after creating or receiving new credentials.

It does **not** disconnect third-party applications: their grants survive it. The account holder disconnects one under **Settings → Connected applications**, and an operator can stop a whole application for everybody with `altero oauth disable <client-id>`. Suspending the account stops its tokens along with everything else.

### Delete an account

Deleting an account removes its personal library. It is refused while the account owns a group, because altero will not guess who should inherit that group.

Deletion is also refused for your own currently signed-in administrator account and where it would remove the last administrator.

## Sign-in providers

**Administration → Sign-in providers** configures OpenID Connect and SAML 2.0 for browser sign-in.

Directory sign-in creates a browser session. The v3 API accepts API keys and
OAuth access tokens, never that session cookie. Zotero Desktop still gets its
API key from **Settings → API keys**.

### Before adding a provider

Set `ALTERO_PUBLIC_URL` first. The administration screen shows the redirect/callback address that must be registered with the identity provider.

Provider creation, updates and sign-in refuse to proceed without this setting.
OIDC callbacks, SAML assertion recipients and the SAML service-provider identity
always use it; request host headers cannot supply a substitute.

A callback mismatch is rejected by the provider before altero can complete sign-in.

Live integration tests cover Keycloak and SimpleSAMLphp. Other provider recipes
below are marked unverified. See the [fixture scope](https://github.com/eseifert/altero/blob/master/tests/idp/README.md)
for the flows actually checked.

### OpenID Connect

Store the client credentials and provider settings in the administration screen. Client secrets are write-only: the interface can replace a secret but does not display the existing value.

Copy the provider's exact `issuer` value from its discovery document, including
any trailing slash. Issuers must match in configuration, discovery and ID
tokens, as required by
[OpenID Connect Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html#ProviderConfigurationValidation).

### SSO-only mode

Set `ALTERO_SSO_ONLY=true` to require an OIDC or SAML provider for browser
sign-in. `ALTERO_PUBLIC_URL` is required. Desktop API keys and connected
applications continue working; this setting controls browser authentication.

Before enabling it:

1. Configure and test an enabled provider, including fresh identity confirmation for sensitive actions.
2. Connect existing accounts under **Settings → Sign-in and security**, or choose whether the provider may create accounts.
3. Keep shell access for recovery, then enable the setting and restart.

Matching email addresses never links identities. With no working provider,
users cannot sign in. Initial local registration is disabled too.

In this mode, local passwords, passkeys, registration, reset links, email
changes and local second factors are unavailable. Manage second factors at the
provider. Old local sessions must sign in through a provider; sensitive actions
require fresh provider confirmation, valid for five minutes. After a provider
round trip, reselect an archive or reenter form data if navigation cleared it.

The last enabled provider linked to an account cannot be removed. Existing
local credentials are retained: to recover from provider failure, disable
`ALTERO_SSO_ONLY` from the server shell, restart, and use account-recovery
commands. This mode does not add continuous directory synchronization.

### SAML 2.0

A SAML provider requires:

- the identity provider entity ID;
- the sign-on URL; and
- one or more signing certificates in PEM form.

Multiple certificates can be stored during signing-key rollover.

Register the screen's **Callback address** as the assertion consumer service
(ACS), using HTTP-POST. For a provider whose short name is `campus`, this is
`<public_url>/web/auth/saml/campus/acs`. The service provider entity ID is
`public_url` without a trailing slash.

When linking an account or confirming identity, complete the return to altero
in the same signed-in browser within two minutes. An expired handoff requires
starting again. See the [SAML session handoff](compatibility.md#finishing-saml-account-linking-with-the-browser-session)
for protocol details.

The SAML implementation is deliberately limited to:

- SP-initiated sign-in;
- signed, unencrypted assertions; and
- local sign-out only, with no SAML Single Logout.

### Account creation and deprovisioning

Automatic account creation through a provider is **off by default**. Turning it on allows identities accepted by that provider to create local altero accounts.

A provider can also require a claim and value, such as an entitlement or group. On each sign-in, altero checks the requirement. If a previously linked user no longer has the required claim, the local account is suspended, which also stops existing Zotero API keys.

This check happens at sign-in time. It cannot detect a person who leaves the organization and never attempts to sign in again; administrators must handle that case through the Accounts screen or another operational process.

It also needs a token or assertion to check. If the directory refuses sign-in
before returning one, altero cannot observe the missing claim and that attempt
does not suspend existing local sessions or API credentials.

Removing a provider removes the account links to it, not the local accounts themselves.

### Provider recipes

Use these settings with your own HTTPS addresses and client credentials. The
examples use `https://library.example.org` for `ALTERO_PUBLIC_URL`. Choose a
**Short name** before registering the callback; it becomes part of that address.

| Protocol | Address to register at the provider |
| --- | --- |
| OIDC | `https://library.example.org/web/auth/sso/<short-name>/callback` |
| SAML, HTTP-POST ACS | `https://library.example.org/web/auth/saml/<short-name>/acs` |
| SAML service provider entity ID | `https://library.example.org` |

For OIDC, create a confidential web client using authorization code and S256
PKCE, accepting `client_secret_post` at its token endpoint. Altero sends the
secret in the form body. Set **Scopes** to `profile email`; `openid` is added
automatically. The default claim names are `preferred_username`, `name` and
`email`. Keep ID tokens unencrypted. Discovery and token endpoints must be
reachable by the altero server, as well as the sign-in page by the browser.

Choose whether the provider may create accounts. With creation off, an existing
user first connects the provider from **Settings → Sign-in and security**.
Matching an email address never links accounts automatically. **Required claim**
names a literal top-level claim or SAML attribute; **Required value** must match
the string or one entry in its list exactly.

#### Keycloak

**Tested provider:** OIDC and SAML integration tests cover Keycloak.
See [test scope](https://github.com/eseifert/altero/blob/master/tests/idp/README.md)
for the exercised flows and limits.

For OIDC, create an `openid-connect` client in the chosen realm. Enable client
authentication and the standard authorization-code flow, require S256, and
register the exact callback. Copy the client ID and generated secret into
altero. Set **Issuer** to `https://<keycloak-host>/realms/<realm>`.
[Keycloak client settings](https://www.keycloak.org/docs/latest/server_admin/index.html#_oidc_clients)
describe these controls.

To require a group, add a group-membership mapper to this client's scope,
emitting `groups` in the ID token or UserInfo. With full paths disabled, set
altero's requirement to `groups` and the group name, such as `researchers`.

For SAML, create a `saml` client whose ID is altero's entity ID. Register the
ACS, force POST responses and persistent NameIDs, enable assertion signing
with RSA-SHA256, and disable assertion encryption and required client
signatures. Copy the IdP issuer, HTTP-Redirect sign-on endpoint and signing
certificate from the realm's `/protocol/saml/descriptor` into altero. Map user
attributes to `preferred_username`, `name` and `email` as needed. The fixture's
[realm settings](https://github.com/eseifert/altero/blob/master/tests/idp/altero-realm.json)
show the tested mapper and protocol choices.

#### Microsoft Entra ID

**Unverified with altero.** This recipe follows Microsoft's
[authorization-code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
and [OIDC endpoints](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc).

Register a single-tenant application in **App registrations**. Add a **Web**
redirect URI with altero's exact OIDC callback, and create a client secret.
Enter the application/client ID and the secret's **value**, not its identifier,
in altero. Use `https://login.microsoftonline.com/<tenant-id>/v2.0` as **Issuer**,
with the actual tenant UUID. The `common` and `organizations` endpoints do not
provide the fixed issuer this configuration requires. Use authorization code;
implicit/hybrid ID-token delivery is not needed.

For an entitlement, define an [app role](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps)
with a value such as `altero`, assign test users to it, and set **Required claim**
to `roles` and **Required value** to `altero`. The role must appear in the ID
token. Altero does not resolve group-overage links through Microsoft Graph.

#### Okta

**Unverified with altero.** Follow Okta's
[web application registration](https://developer.okta.com/docs/guides/sign-into-web-app-redirect/node-express/main/).
Choose OIDC and **Web Application**, enable authorization code, register the
exact callback, and assign the intended users or groups to the application.

Configure the client's `token_endpoint_auth_method` as `client_secret_post`
using Okta's client settings/API; its default is `client_secret_basic`, while
altero sends form credentials. See
[client authentication](https://developer.okta.com/docs/api/openapi/okta-oauth/guides/client-auth).
Enter the client ID and secret in altero.

Use the org issuer `https://<your-okta-domain>` for ordinary sign-in. If using a
custom authorization server, copy its exact issuer, such as
`https://<your-okta-domain>/oauth2/<authorization-server-id>`, and configure its
access policy for this client. Do not assume `/oauth2/default` exists in every
deployment; see [authorization servers](https://developer.okta.com/docs/concepts/auth-servers/).
Additional required claims must actually be emitted for this client and scope.

#### authentik

**Unverified with altero.** Create an application and an **OAuth2/OIDC** provider
using the [provider wizard](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/create-oauth2-provider/).
Choose a confidential client, set the exact callback as a strict redirect URI,
and select the `openid`, `profile` and `email` scope mappings. Copy the client
ID and secret into altero; leave token encryption disabled.

Keep the default per-provider issuer mode and a stable subject identifier.
Set altero's **Issuer** to
`https://<authentik-host>/application/o/<application-slug>/`, including the final
slash. Copy the actual value from discovery. Global issuer mode uses a
different discovery location from its issuer and does not fit altero's
issuer-based discovery. See authentik's
[issuer modes and endpoints](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/#issuer-mode).
Configure application access bindings and any required claim for your policy.

#### Shibboleth IdP

**Unverified with altero.** Use SAML 2.0. Give the IdP administrator the entity ID
and HTTP-POST ACS above, and register the service provider in its metadata.
Altero does not publish a metadata endpoint; this minimal descriptor is a
starting point, with your own host and short name substituted:

```xml
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
                  entityID="https://library.example.org">
  <SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"
                   AuthnRequestsSigned="false" WantAssertionsSigned="true">
    <NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:persistent</NameIDFormat>
    <AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        Location="https://library.example.org/web/auth/saml/shibboleth/acs"
        index="0" isDefault="true"/>
  </SPSSODescriptor>
</EntityDescriptor>
```

Enable a [persistent NameID generator](https://shibboleth.atlassian.net/wiki/spaces/IDP5/pages/3199507892/PersistentNameIDGenerationConfiguration)
before the first sign-in; a transient NameID changes the identity between
sessions. For this relying party, use the `SAML2.SSO` profile with
`signAssertions="true"`, `encryptAssertions="false"` and
`encryptNameIDs="false"`, and accept unsigned AuthnRequests. Apply these choices
only to altero's relying party; see
[signing/encryption settings](https://shibboleth.atlassian.net/wiki/spaces/IDP5/pages/3199508797/SecurityConfiguration)
and [SAML 2.0 profile options](https://shibboleth.atlassian.net/wiki/spaces/IDP5/pages/3199508364/ProfileConfiguration-SAML2).

Copy the IdP entity ID, HTTP-Redirect sign-on URL and signing certificate from
its metadata into altero. Arrange release of username, display-name and email
attributes. If their `Name` or `FriendlyName` values are `eppn`, `displayName`
and `mail`, use those as altero's three claim names; otherwise use the actual
released names. Altero reads attributes from the signed assertion and makes no
separate attribute-query request.

#### Check a configuration

Use a test account to sign in twice, signing out of altero between attempts.
Both visits should reach the same local account. For an existing account with
creation disabled, test linking from Settings first. Confirm that the provider
also supports a fresh sign-in when Settings asks for proof to issue an API key.

If using a required claim, test both an allowed and a denied identity. Losing
that claim after linking suspends the local account at its next sign-in;
restoring the claim alone does not reinstate it. An administrator must
reinstate the account. This is still a sign-in-time check, not continuous
deprovisioning. See [account creation and deprovisioning](#account-creation-and-deprovisioning).

## Third-party applications

Register applications that should receive limited, expiring library access.
Set `ALTERO_PUBLIC_URL` first, then use:

```sh
uv run altero oauth add notebook \
    --name "Notebook" \
    --redirect-uri https://notebook.example.com/auth/callback \
    --scope openid --scope profile --scope library.read
uv run altero oauth list
uv run altero oauth disable notebook
```

Account holders approve access in their browsers and can disconnect an
application under **Settings → Connected applications**. See
[Connecting other applications](oauth.md) for scopes, registration and developer details.

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

### What cleanup removes

Trash cleanup permanently deletes eligible objects and records the deletions
for syncing clients. It checks again for items restored or changed during the
sweep. Age is measured from the last server-recorded item change, rather than
a separate time of trashing.

The sweep also removes expired sessions, codes, links, invitations, download
permissions and private undo snapshots. These have their own expiry times.

Unreferenced attachment files require a separate cleanup action in **Storage**;
timed retention does not remove them. A grace period protects files belonging
to uploads still in progress.

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

Exporting holds library writes until the archive is built, so its contents
describe one consistent version. The lock is released before downloading.
Restoring also locks the target library before checking or replacing its contents.

Importing into a non-empty target is refused unless `--replace` is used.

The browser exposes equivalent import/export operations under **Settings → Import and export**.

### Move a personal library from zotero.org

This is a one-time migration. It does not keep the two servers synchronized
afterwards. Finish syncing to zotero.org before importing, and pause edits
until the clients have moved to altero. Continuous two-way sync is unsupported;
a scheduled one-way refresh is future work. See
[the verdict and replacement-import limits](compatibility.md#continuous-sync-with-zoteroorg).

If possible, create the altero account with the same numeric user ID that zotero.org uses:

```sh
uv run altero user add <username> --id <zotero.org-user-id>
uv run altero migrate zotero <username> --replace
```

The migration asks for a zotero.org API key with read access to the personal library. The key is prompted for rather than placed on the command line.

The migration preserves Zotero object keys and versions so an already-synchronized desktop client can continue from the same state.

If the account numbers differ, linking the existing profile is refused. Use an account with the original number or a fresh profile, as explained in [A profile that has synced before](clients.md#a-profile-that-has-synced-before).

Only the personal library is imported. Attachment bytes that zotero.org does not hold cannot be downloaded; the migration lists those items and brings the attachments across without their files.

> [!IMPORTANT]
> If attachment files were synchronized over WebDAV, zotero.org holds none of them. It answers 404 for every one, so the whole library arrives without files. The metadata is complete: item keys, `md5` and `mtime` are all preserved. Either keep the WebDAV server for files, or move the files into altero from a client that still has them. See [File syncing](clients.md#file-syncing).

### After recreating the database

Pause other clients before recovery. A desktop may remember a later library
version than a recreated database or older archive. Raising the server's
library version fixes that counter mismatch, but **does not** make older item
versions replace newer desktop caches.

If a surviving desktop holds the complete authoritative library:

1. Back up its data directory and the server before proceeding.
2. Raise the server library version above the value remembered by that desktop:

   ```sh
   uv run altero library set-version user 1 <higher-version>
   ```

3. Use Zotero's **Restore to Server** to upload the surviving desktop's complete copy.
4. Verify metadata and attachment bytes before reconnecting other clients.

This command only raises the counter; it recreates no lost objects or files.
Do not resume normal sync assuming the version change restored data. Without a
complete surviving copy, restore from a verified backup and plan how each client
will obtain that state. Automatic rewind of synced desktop objects is unsupported.

## Group policy

A group has three Zotero-compatible policy settings:

| Setting          | Values                      | Controls                        |
|------------------|-----------------------------|---------------------------------|
| `libraryReading` | `members`, `all`            | Who may read the library        |
| `libraryEditing` | `members`, `admins`         | Who may edit objects            |
| `fileEditing`    | `none`, `members`, `admins` | Who may upload attachment files |

The group `type` is `Private`, `PublicOpen` or `PublicClosed`.

A public group is readable without a key only when the group is public **and** `libraryReading` is `all`.

Membership remains a ceiling over key permissions: a key that grants access to all groups still cannot read a group the account does not belong to.

### Per-member permissions

altero can apply an additional restriction to one member:

| Permission | Meaning                                                      |
|------------|--------------------------------------------------------------|
| `inherit`  | Use the normal group policy                                  |
| `read`     | Read only                                                    |
| `add`      | Create and change, but do not remove or trash                |
| `own`      | Create freely; change or remove only items that member added |

From the shell:

```sh
uv run altero group member <group> <username> --permission read
uv run altero group permission <group> <username> add
uv run altero group members <group>
```

These permissions can only restrict what the group policy already allows. They do not elevate a member above the group's normal policy.

Only the read-only state maps cleanly onto a permission the Zotero sync client understands. `add` and `own` are enforced server-side; a client that attempts a forbidden operation receives a sync error explaining the restriction. See [Compatibility notes](compatibility.md#finer-roles-for-one-member).
