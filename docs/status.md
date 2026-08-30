# What works

This page is the feature-level status of altero's Zotero v3 compatibility.

**Short version:** ordinary Zotero Desktop synchronization is the target; the official mobile apps are not supported.

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
| Browser interface                         |   ✅   | Library browsing, account settings, groups and administration                                                            |
| OIDC and SAML browser sign-in             |   ✅   | Sign-in only; never a v3 API credential                                                                                  |
| OAuth 2.0 and OIDC provider               |   ✅   | Scoped tokens for third-party applications, confinable to chosen libraries and collections; requires a stable public URL |
| Passkeys and optional second factors      |   ✅   | Passkeys require a stable public URL                                                                                     |
| Import a personal library from zotero.org |   ✅   | Preserves object keys and versions                                                                                       |
| Zotero iOS and Android apps               |   ❌   | No runtime alternate API host in the official apps                                                                       |

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

## Additional altero features

These are not required for basic Zotero compatibility but are available on an altero instance:

- browser-based account and API-key management;
- instance administration without library-wide superuser access;
- OpenID Connect and SAML 2.0 browser sign-in;
- an OAuth 2.0 and OpenID Connect authorization server, so a third-party application can be given scoped, expiring access instead of an API key, confinable to chosen libraries and collections, with RP-initiated sign-out and a device grant for a machine that has no browser;
- passkeys, authenticator-app second factors and email codes;
- per-member group permissions such as read-only, add-without-remove and own-items-only;
- group activity and opt-in notifications;
- configurable retention;
- server-side tag rename;
- single-collection sharing links;
- storage reporting; and
- whole-library export/import and migration from zotero.org.

## Not implemented

- Zotero's **Note HTML** and **Note Markdown** translators. These create a note rather than an ordinary bibliography/export response.
- The official Zotero iOS and Android clients, because they cannot be pointed at an alternate API host at runtime.

## Client requests without a reference server implementation

Two client behaviors do not have a corresponding implementation in the public dataserver source:

- `GET /retractions/list`; and
- the streaming WebSocket service.

altero currently answers the retractions request with `404`. Zotero logs the failure and continues syncing. The streaming API is implemented from the published protocol and observed client behavior.

## Library versions and concurrent writes

Writes to a library are serialized so one request advances the library by one version, even when that request changes several objects. This is important because Zotero synchronization uses the library version as its consistency boundary.

See [Database schema](schema.md#concurrency) for the implementation details.
