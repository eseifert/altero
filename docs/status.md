# What works

Use this page to check whether altero supports your workflow. For installation,
start with [Getting started](getting-started.md).

Ordinary Zotero Desktop synchronization is the main target. Automated desktop
acceptance runs on Linux. Basic sync has community reports on Windows and
macOS; broader conflict and recovery coverage on those platforms remains
unverified. Mobile apps need a separate build pointed at your server.

Keep a current backup of important libraries and don’t rely on altero as your
only copy yet. Recorded results and their limits are in
[desktop compatibility checks](client-compatibility.md),
[Podman testing](testing-podman.md#recorded-run) and
[release validation history](release-history.md).

## User-facing capabilities

| Capability                                | Status | Notes                                                                                                                    |
|-------------------------------------------|:------:|--------------------------------------------------------------------------------------------------------------------------|
| Zotero Desktop synchronization            |   ✅   | Items, collections, tags, saved searches and deletions                                                                   |
| Notes and annotations                     |   ✅   | Included in normal item synchronization                                                                                  |
| Attachment file sync                      |   ✅   | Files stored once per digest                                                                                             |
| Full-text upload and search               |   ✅   | Uses the database rather than Elasticsearch                                                                              |
| Group libraries                           |   ✅   | Includes group policy and membership                                                                                     |
| My Publications                           |   ✅   | Includes browser publishing and profile pages                                                                            |
| Citations and bibliographies              |   ✅   | CSL-based styles and Zotero-compatible formats                                                                           |
| Zotero export formats                     |   ✅   | API and browser export support                                                                                           |
| Browser interface                         |   ✅   | Library browsing, item and note editing, file uploads, account settings, groups and administration; installable as an app |
| OIDC and SAML browser sign-in             |   ✅   | Sign-in only; never a v3 API credential                                                                                  |
| OAuth 2.0 and OIDC provider               |   ✅   | Scoped tokens for third-party applications, confinable to chosen libraries and collections; requires a stable public URL |
| Passkeys and optional second factors      |   ✅   | Passkeys require a stable public URL                                                                                     |
| Import a personal library from zotero.org |   ✅   | Preserves object keys and versions                                                                                       |
| Zotero iOS and Android apps               |   ⚠️   | Unofficial: needs a build pointed at altero; Android reported working on a device, iOS untested                          |

## Synchronization and API behavior implemented

altero implements the parts of the v3 API needed by the desktop client, including:

- API-key authentication and per-library permissions;
- OAuth 2.0 access tokens as a second credential for the same endpoints;
- personal and group library discovery;
- item, collection, saved-search and tag reads;
- `json`, `atom`, `keys` and `versions` response formats;
- pagination, sorting, `since` and version-aware conditional requests;
- item, collection and saved-search writes with version preconditions;
- deleted-object synchronization;
- library settings;
- attachment full text;
- the three-step attachment file protocol;
- the streaming API at `/stream`;
- My Publications and publication visibility;
- citations, bibliographies, CSL JSON and Zotero export formats;
- group creation, membership and group policy;
- rate limiting when enabled; and
- API version negotiation.

The compatibility reference documents behavior that differs from the public API documentation or that had to be learned from the real client or server: [Compatibility notes](compatibility.md).

Three explicit choices: [library tag counts include trash](compatibility.md#tag-counts-and-the-trash),
[group renames notify clients](compatibility.md#group-renames-notify-connected-clients),
and [Unfiled is a browser-only view](compatibility.md#the-desktop-clients-three-extra-views).

## Additional altero features

The browser adds account management, collection-sharing links, group activity,
per-member restrictions, configurable retention and storage reporting. Library
archives and migration from zotero.org support moving data between servers.
See the [web guide](web-interface.md) and [administration guide](administration.md).

## Sign-in and authorization verification

Live integration tests cover Keycloak and SimpleSAMLphp sign-in, and Authlib
as a client of altero's authorization server. Other provider recipes are
explicitly marked unverified in [Administration](administration.md#provider-recipes).

The recorded OpenID Foundation assessment passed Config OP but did not pass
Basic OP. altero is not OpenID-certified; see [results and limits](oidc-conformance.md).

## Not implemented

- Storage quotas: usage is reported, but no per-library quota is enforced.
- Continuous replication with zotero.org in either direction. The existing personal-library import is a one-time copy; [one-way refresh remains future work](compatibility.md#continuous-sync-with-zoteroorg).
- Zotero's **Note HTML** and **Note Markdown** translators. These create a note rather than an ordinary bibliography/export response.
- Zotero-hosted read-aloud speech synthesis and credit services (`/tts/...`).
- Legacy password-to-key creation (`POST /keys`); use desktop browser linking or an API key.
- Legacy `removestoragefiles`; synced attachment removal follows item deletion.

## Client requests without a reference server implementation

Two client behaviors do not have a corresponding implementation in the public dataserver source:

- `GET /retractions/list`; and
- the streaming WebSocket service.

altero currently answers the retractions request with `404`. Zotero logs the failure and continues syncing. The streaming API is implemented from the published protocol and observed client behavior.

## Library versions and concurrent writes

Writes to a library are serialized so one request advances the library by one version, even when that request changes several objects. This is important because Zotero synchronization uses the library version as its consistency boundary.

See [Database schema](schema.md#concurrency) for the implementation details.
