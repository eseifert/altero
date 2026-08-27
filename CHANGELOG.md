# Changelog

All notable changes to altero, newest first. Versions follow
[semantic versioning](https://semver.org/); everything below 1.0.0 is
development history, tagged retroactively at the points where the server
gained a capability worth naming.

## [Unreleased]

- The interface splits three of its languages by the territory they are read in: American and British English, Brazilian and European Portuguese, and Simplified and Traditional Chinese, which are the same three Zotero splits. Fifteen catalogues where there were twelve, the domain words taken from Zotero's own `chrome/locale`, so a British reader empties the Bin and a Brazilian saves an *arquivo*. A tag with no catalogue of its own is sent where it reads — `en-AU` to British, `zh-HK` to Traditional, `pt-AO` to European — and a bare `en`, `pt` or `zh` goes where CLDR's likely subtags send it; a stored `en`, `pt` or `zh` is migrated to the variant it meant. Everywhere else a region still reaches dates and nothing else, and `de-AT` is German.
- Third-party applications can be given scoped, expiring access to a library instead of an account's API key: altero is now an OAuth 2.0 authorization server and OpenID Connect provider, with authorization code and PKCE, refresh-token rotation, RS256 ID tokens at `/oauth/jwks.json`, and a consent screen that lives in the web interface — so signing in there goes through the same second factor, passkey or single sign-on as everywhere else. Applications are registered by an operator with `altero oauth add`, and each person can see and disconnect theirs under Settings. The v3 API accepts these tokens alongside API keys and still never accepts a cookie. Proposed, and first implemented, by [@sadgen](https://github.com/sadgen) in [#8](https://github.com/eseifert/altero/pull/8).
- Attachment downloads survive Zotero's April 2026 client rewrite: the redirect now hands out a short-lived permission for the one file, at `/storage/download/<key>`, rather than a location only an API key can open. The client no longer follows that redirect but makes a second request carrying no headers, so every attachment failed to download; the account key stays out of the URL, and so out of every reverse proxy's access log. Reported and first diagnosed by [@sadgen](https://github.com/sadgen) in [#7](https://github.com/eseifert/altero/pull/7).
- The container image is published as `ghcr.io/eseifert/altero` for x86-64 and arm64, so running altero needs neither a checkout nor a build; `docker/compose.yaml` pulls it and `docker/compose.build.yaml` builds from source instead.
- Deployment documents what a small instance costs in memory and disk, and carries reverse-proxy configurations for nginx, Caddy and Traefik, including the upload limit and the WebSocket upgrade that `/stream` needs.
- citeproc-py upgraded to 0.11.0 which allows to drop a workaround for a doubled full stop after an initialled name.
- The documentation is reorganized around six sections: an index, a getting-started page, and the browser guide split into one page per part of the interface.
- The documentation is published as a site at https://eseifert.github.io/altero/, built by Zensical and deployed on every push, with a version for each release once 1.0.0 is out.

## [1.0.0-alpha.1] — 2026-08-19

The first release meant to be used by somebody other than its author.

- Single sign-on over OpenID Connect and SAML, plus passkeys, all kept out of the v3 API.
- Finer roles for a single group member, and one collection shared as a read-only page.
- A password reset by email link, and a second factor that can arrive as an emailed code.
- Every export format zotero.org serves, in the browser as well as the API.
- Danish, Dutch, Italian, Polish, Russian and Chinese join the interface languages, each counting plurals its own way.

## [0.9.0] — 2026-08-11

- An instance administrator: what the server runs, what it costs, how long it keeps things, and the account lifecycle.
- Stored bytes nothing references any more can be deleted, and a password set by link.
- The browser writes a library's items out as a file, in any format, over the item list's own query.
- A rig that decides whether two clients and the server hold the same library.
- The interface gathered into drawn glyphs, with targets a finger can hit.

## [0.8.0] — 2026-08-09

- Dragging in the item list, by mouse and by finger, carrying items and collections.
- Several rows picked out at once and moved as one errand.
- Both panes resizable, and the widths remembered.
- Publishing to My Publications the way the desktop client's wizard does, licence and all.
- The sidebar arranged as Zotero's web library arranges it.

## [0.7.0] — 2026-08-06

- A personal library read out of zotero.org and restored over this one.
- A tag renamed, and collections made and removed, from the browser.
- A POSTed batch read as a batch of patches, which is what the client sends.
- An item's fields in the order the client can read them, and the redirect it reads file metadata from.

## [0.6.0] — 2026-08-05

- Groups, by API key, from the browser and from the command line, with invitations.
- A library archive out and back in.
- Atom, and the streaming API telling a client the moment a library changes.
- One digest per burst of group activity, to the people who asked and did not cause it.
- Full-text search answering with the item holding the text.

## [0.5.0] — 2026-08-04

- Citations and bibliographies on citeproc-py, plus BibTeX, BibLaTeX and RIS.
- A library the browser can actually be used to read.
- English, German, French, Spanish, Portuguese and Japanese, dates the reader's way, and Zotero's own names for fields.
- IBM Plex Sans served from here, and an interface usable without sight or a mouse.

## [0.4.0] — 2026-08-03

- Accounts a person can sign in to: Argon2id, TOTP, and no account enumeration.
- The web interface begins, under `/app` and nowhere else, built in the image and checked in CI.
- Cookie authentication with its own read endpoints, kept off the v3 API.
- Mail, settings, notifications and invitations; a Zotero client approved from the browser.
- People managing their own API keys, with when and where each was last used.

## [0.3.0] — 2026-08-02

- An instance that can be deployed and asked whether it is ready.
- A library moved between instances, or rebuilt and lifted back over its clients.
- The client no longer hands its altero key to zotero.org.
- A whole sync cycle driven over a real socket.
- A page's related data and counts fetched once rather than once per row.

## [0.2.0] — 2026-07-31

- The Zotero desktop client obtains a key and connects.
- Partial item uploads applied instead of a full object demanded.
- Compressed bodies, zipped snapshot uploads and absolute upload URLs.
- The batch full-text upload and a bare tag deletion.

## [0.1.0] — 2026-07-31

- Version 3 of the Zotero Web API: items, collections, saved searches, tags, the delete log, library settings, full-text content and the file protocol.
- Object keys, search syntax, pagination, authentication and access control.
- The item type schema and the endpoints derived from it.
- Concurrent writes serialised, so one request produces exactly one new version.
- A command line for provisioning, CI, and the documentation to go with it.

[1.0.0-alpha.1]: https://github.com/eseifert/altero/releases/tag/v1.0.0-alpha.1
[0.9.0]: https://github.com/eseifert/altero/releases/tag/v0.9.0
[0.8.0]: https://github.com/eseifert/altero/releases/tag/v0.8.0
[0.7.0]: https://github.com/eseifert/altero/releases/tag/v0.7.0
[0.6.0]: https://github.com/eseifert/altero/releases/tag/v0.6.0
[0.5.0]: https://github.com/eseifert/altero/releases/tag/v0.5.0
[0.4.0]: https://github.com/eseifert/altero/releases/tag/v0.4.0
[0.3.0]: https://github.com/eseifert/altero/releases/tag/v0.3.0
[0.2.0]: https://github.com/eseifert/altero/releases/tag/v0.2.0
[0.1.0]: https://github.com/eseifert/altero/releases/tag/v0.1.0
