# What works

This page is the feature-level status of altero's Zotero v3 compatibility.

**Release:** 1.0.0-beta.7. Two real Zotero 10.0.7 profiles passed 72
database/scenario combinations and 838 phases on Linux, across SQLite and
PostgreSQL 18.4. This verifies the recorded transitions, not every client path
or platform. See
[desktop compatibility coverage and gaps](client-compatibility.md).

**Windows and macOS remain untested by the project's desktop acceptance
suite.** A [community report](https://github.com/eseifert/altero/issues/49#issuecomment-6555801282)
describes basic sync working with Zotero 10.0.7 and altero beta.7 on both;
it does not establish conflict, file-recovery or full acceptance coverage.
To contribute a reproducible platform result, follow the
[two-client test and reporting checklist](testing-two-clients.md#windows-and-macos-reports).

Populated databases from every beta through beta.7 pass direct upgrades to the
current development schema on SQLite and PostgreSQL, including attachment
downloads and repeat startup. See the [upgrade matrix and limits](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#beta-upgrade-validation).

The published beta.7 amd64 image also passes a [rootless Podman check](testing-podman.md#recorded-run)
with SQLite, browser writes, attachment persistence after container replacement
and a changed internal port. The report records the exact image and host;
other Podman configurations need separate evidence.

A file-conflict issue was reproduced in Zotero 10.0.1 and 10.0.6: when both sides
have equal displayed modification dates, choosing Remote can retain and upload
the local bytes. The later run used Zotero Storage at zotero.org; the
[upstream report](https://forums.zotero.org/discussion/134528/bug-selecting-remote-in-a-file-conflict-can-upload-the-local-file)
records the reproduction and file hashes. This equal-date case has not been
rerun on 10.0.7. See [the exercised cases and limits](client-compatibility.md#run-two-real-desktop-profiles).

**Short version:** ordinary Zotero Desktop synchronization is the target; the official mobile apps work through a build of your own, unofficially but supported.

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
- [undo toasts](web/library.md#items) for browser filing and trash changes, guarded against later edits;
- single-collection sharing links;
- storage reporting; and
- whole-library export/import and migration from zotero.org.

## Sign-in and authorization verification

Real Keycloak OIDC/SAML, SimpleSAMLphp SAML and independent Authlib client flows
passed [hosted CI at `fcf8460`](https://github.com/eseifert/altero/actions/runs/41250704073/job/124683435185)
without skipped tests. The [provider recipes](administration.md#provider-recipes)
distinguish that coverage from the unverified Entra ID, Okta, authentik and
Shibboleth setups.

The local OpenID Foundation assessment passed Config OP; Basic OP did not pass.
See the [results and limits](oidc-conformance.md), including the mandatory-PKCE
profile mismatch. These checks establish no OpenID certification.

## Not implemented

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
