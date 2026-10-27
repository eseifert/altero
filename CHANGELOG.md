# Changelog

All notable changes to altero, newest first. Versions follow
[semantic versioning](https://semver.org/); everything below 1.0.0 is
development history, tagged retroactively at the points where the server
gained a capability worth naming.

## [Unreleased]

- The browser interface writes notes, standalone or under an item, with Zotero Desktop's toolbar and keys, saving as you type ([notes]).

## [1.0.0-beta.5] — 2026-10-27

This version edits items in the browser — fields, type, creators, tags, related
items and new items — and shows changes made elsewhere as they happen. It also
fixes a sync stop in every earlier beta: changing an item's type in Zotero
Desktop so that it lost fields stopped that library syncing. Pull the new image:
it runs Python 3.14.10, which distrusts the leaked eMudhra certificate keys.
Upgrading needs no database changes.

- Building from source needs uv 0.13.4, Python 3.14.10 and Node 24.22.1, which distrust the leaked eMudhra keys ([source]).
- altero makes its outbound requests with httpx2 in place of httpx, verifying TLS against the system's trust store instead of certifi's.
- The browser interface can be installed as an app on phones and computers, and opens offline; no library data is kept on the device ([install]).
- Desktop acceptance covers items edited in the browser reaching both desktops, and a desktop edit winning a race: 31 scenarios.
- An open browser page shows changes made elsewhere — a desktop syncing, a group member — without a reload ([editing]).
- The browser's item list offers *Show more* until every item is shown; it stopped after the second page, hiding the rest.
- The browser's item list is worked with the arrow keys, Home, End, Enter and F2, as on the desktop; `?` lists the shortcuts ([items]).
- An edit in the browser over a change made elsewhere is saved when they differ, and asks which version to keep when they clash ([editing]).
- The browser interface makes new items: **+** over the item list, recently used types first, filed into the open collection ([editing]).
- The browser interface edits an item's tags, offering the library's tags as you type, and shows colours set in Zotero Desktop ([editing]).
- The browser interface relates items under **Related**: search the library to add one, remove one, or open it ([editing]).
- The browser interface edits an item's creators: role, one or two name fields, add, remove, and reorder by drag or menu ([editing]).
- Icons in the browser interface are larger: 22px in toolbars and the sidebar instead of 16–18px, in slightly larger buttons.
- The browser interface edits an item's fields and changes its type, saving each field as you leave it ([editing]).
- Changing an item's type in Zotero Desktop no longer stops sync when the item loses fields; fields and creators move as on zotero.org.
- Desktop acceptance covers a lost parent, a child moved out to the library and a type change: 30 scenarios.
- Uploads are held to zotero.org's rules for what may be a child of what; annotations on EPUBs and HTML snapshots are accepted ([parents]).
- A note or attachment moved out to the library in Zotero Desktop is top-level here too; it used to stay under its old parent.
- An upload naming a missing parent or collection fails with 409 and names it, so Zotero Desktop uploads it and retries ([dependencies]).
- An item created from the `/items/new` template no longer keeps its empty creator; other nameless creators are refused, as on zotero.org.
- A v3 item write without `dateModified` that changes nothing keeps its version, as on zotero.org.

## [1.0.0-beta.4] — 2026-10-26

This version closes two ways somebody else's content could run a script in your
browser: a note, and an attached web page. Upgrading needs no database changes.

- Notes and citations can no longer run a script in the browser; `bib` and `citation` escape markup in fields, as zotero.org does. Reported by [@arminbahl] in [Issue#30].
- Attachments opened in a browser tab run no scripts, and the browser interface sends a Content-Security-Policy ([headers]).
- Cases, emails and statutes show their titles throughout the browser interface instead of “(untitled)” ([Issue#22]).
- The browser interface is translated into 17 more languages, 48 in all.
- The container image is built on Debian 13 (trixie), with OpenSSL 3.5 instead of the end-of-life 3.0 ([Issue#29]).
- The container image is about 60 MB smaller: uv, which only the build needs, stays out of it.
- The container image runs on its own for a quick trial, keeping a SQLite database on its `/data` volume.
- The library draws the shape of its rows while they load.
- A profile's item types meet WCAG contrast; found by the new browser tests with axe.
- Item searches ignore case in every alphabet on SQLite too: `über` finds “Über”.
- Tag searches match case, as on zotero.org: `/tags?q=fic` no longer finds “Fiction”.

## [1.0.0-beta.3] — 2026-10-19

This version is mostly about speed: large libraries sync, search, import and
export much faster, and the browser interface starts sooner. Upgrading builds a
search index once, about a minute per 30,000 attachments with text; check the
[database requirements][db-req] first.

- The browser interface is translated into 17 more languages, 31 in all.
- Searching everything, attachments' text included, is up to three times faster, and on PostgreSQL a small library no longer waits on a large one.
- The first sync of a large library starts much sooner: listing what a library of 34,000 items holds takes 0.3 s instead of 17 s.
- Tags and collections list faster in large libraries: the tags of 34,000 items take 0.4 s instead of 26 s.
- Saving and deleting items is faster: deleting 1,000 items takes seconds instead of a minute and a half.
- Restoring a library archive is about 18 times faster; exports, imports from zotero.org and file downloads are quicker too.
- A long bibliography, a large upload or an export no longer holds up everyone else's requests while it runs.
- Many smaller changes make everyday syncing lighter on the server, especially with several accounts.
- The browser interface loads much less before showing the first page, and only the language it displays.
- The browser interface stays responsive while dragging or typing in large libraries; filing or trashing 200 items takes 0.1 s, not 3–4 s.
- The duplicates view opens later pages at once instead of searching the library again for each one.
- Accounts without a password approve Zotero clients by signing in again at their provider. Reported by [@mweber0] in [Discussion#18].
- Confirming who you are through a SAML provider makes it ask again instead of reusing an earlier sign-in.
- Finding duplicates, renaming tags and emptying the trash no longer fail in libraries of more than about 32,000 objects.
- An item carrying the same tag twice is saved with it once instead of failing, as on zotero.org.
- On SQLite, two clients changing a library at the same moment can no longer both succeed; the second syncs again first.
- When SQLite is busy for too long, the Zotero client is told to retry instead of reporting an error.
- Sending settings that did not change no longer makes other devices sync, as on zotero.org.
- Sorting items by the server's modification date works; it used to sort by item key.
- Compressed uploads are capped at 128 MiB, and made-up API keys share their address's rate limit.
- Administrators can size the database connection pool ([configuration][config]).
- Compatibility checks follow Zotero 10.0.6, whose changes since 10.0.5 leave syncing with altero unaffected.

## [1.0.0-beta.2] — 2026-10-03

- Clarify the edit pencil and move interface icons into reusable SVG files.
- Add Korean interface translations using Zotero’s domain terminology.
- Preserve existing note and attachment note text when partial item writes omit the note field.
- Refusing a competing ZIP upload registration preserves another upload's intact, smaller archive.
- Inventory desktop network consumers, record reviewed dispositions and reject unreviewed API changes in CI.
- Replay generated graph, file and credential sequences with two offline clients; shrink only valid reproductions.
- Inject transport failures before and after commits, then restart the server to verify durable recovery.
- Expand desktop acceptance to 27 scenarios covering graph races, credentials, crashes, reader caches and ZIP races.
- Pin checks to [Zotero 10.0.5][desktop-matrix]: 47 SQLite/PostgreSQL combinations pass across 594 desktop phases.
- Recreating a deleted library setting clears its old deletion record so Zotero retains downloaded tag colors.
- Desktop interruption checks kill Zotero's entire process group so child processes cannot continue synchronizing.

## [1.0.0-beta.1] — 2026-10-02

The first beta adds automated checks against the original desktop code and two
real Zotero profiles. All eight desktop scenarios passed with Zotero 10.0.1 and
PostgreSQL 18.4, across 114 phases. Coverage is not exhaustive.
Keep a current backup of important libraries and don’t rely on altero as your
only copy yet.

- Include built web assets in source archives so wheels serve `/app/`; release checks verify public archive contents.
- Document Zotero 10.0.1's file-conflict bug: equal displayed dates can make Remote retain local bytes.
- Two real desktops test conflict dialogs, groups, object graphs, download recovery, concurrent writes and credential relinking.
- Return object-level 404s for versioned writes to deleted items, collections and searches so Zotero reconciles remote deletions.
- Include the attachment version in competing uploads' 412 responses so Zotero can resolve file conflicts.
- Expand checks to every schema type, files, full text, streaming and seeded replay; detect all seven protocol mutations.
- Return absolute attachment download locations, verified with Zotero's original ZFS transfer code.
- Fix group pagination and missing Link headers so Zotero's account preferences can read groups.
- Execute original Zotero functions to check permissions, cached versions and watermarks; report unmapped source consumers.
- Honor desktop group edit permissions via `admins`/`members` and refresh cached groups. Found by [@alpichlabs] in [PR#14].
- Document working Android sync via [zotero-self-hosted-sync], a patch bundle by [@raphaelbahat].
- Document unofficial, supported iOS and Android use through custom builds pointed at altero.
- Fix mobile sign-in by including a query in the login URL before Android appends `&app=1`.
- Serve missing file digests and mtimes as null so Android can upload attachments. Reported by [@raphaelbahat] in [Issue#13].
- Support mobile file uploads with `params=1` authorization and multipart bodies. Reported by [@raphaelbahat] in [Issue#13].
- Write uploads and restores atomically so interrupted transfers leave no partial files. Reported by [@raphaelbahat] in [Issue#11].
- Add Ukrainian interface translations with three plural forms and Zotero's terminology.
- Verify stored bytes when registering uploads, refusing incomplete or lost writes so clients can retry.

## [1.0.0-alpha.3] — 2026-09-14

Still an alpha, and the first release shaped by other people running it: two
defects that stopped a desktop client dead are fixed, and the documentation
answers what the readers who found them had to ask.

- Unlinking a client works again: revoking a key the login handshake handed out answered 500, which is every key a desktop client holds. Reported by [@ScatteredComet] in [Discussion#5].
- Deployment cites a reader's NixOS configuration for Podman.
- The image is published in the Docker format, so Podman reads the health check it carries.
- Deployment documents running altero under Podman.
- The Zotero linking screen is translated throughout.
- The image's health check follows `ALTERO_PORT`.
- Linking a profile that synced elsewhere says what to do.
- Creating an account now says how to give it a password.
- A confidential OAuth client can present its secret as HTTP Basic, which RFC 6749 §2.3.1 requires a server to accept.
- A file whose digest an attachment already claims can be uploaded: the question is asked of the store rather than of the item, so a library migrated from zotero.org with its files on WebDAV can send them at last.
- The migration summary says why files are missing when they synced over WebDAV, in all twelve languages, and how to get them here.
- The documentation says how attachment files sync, and what to do about a library whose files are on WebDAV.
- Every `ALTERO_` setting in `docker/.env` now reaches the container, rather than only the handful `docker/compose.yaml` names.
- The documentation lists every configuration setting with its default, and how to set it from `config.py`, the environment or Docker.

## [1.0.0-alpha.2] — 2026-08-29

Still an alpha: the first one has not been used enough to say the server is
ready, and this one adds to what has to be tried.

- An OAuth grant can be confined to particular libraries or collections.
- A credential that gave up notes or file access is now held to it: without `notes` a note is a 404 and appears in no listing, and without `files` the attachment bytes are refused.
- A device with no browser can be authorized from one somewhere else: RFC 8628, on the same consent screen every other application gets.
- An application can send somebody to `/oauth/logout` to end their browser session, holding an ID token this server issued as proof it may ask.
- An application signing somebody in can be told which groups they belong to: a `groups` claim, behind an identity scope that reaches no library.
- The interface splits English, Portuguese and Chinese by the territory they are read in, as Zotero does.
- Third-party applications get scoped, expiring access to a library instead of an API key: OAuth 2.0 with PKCE and OpenID Connect. By [@sadgen] in [PR#8].
- Attachment downloads survive Zotero's April 2026 client rewrite: the redirect hands out a permission for the file, not the account key. By [@sadgen] in [PR#7].
- The container image is published as `ghcr.io/eseifert/altero` for x86-64 and arm64, so running altero needs neither a checkout nor a build.
- Deployment documents what a small instance costs in memory and disk, and carries reverse-proxy configurations for nginx, Caddy and Traefik.
- citeproc-py upgraded to 0.11.0 which allows to drop a workaround for a doubled full stop after an initialed name.
- The documentation is written in American English throughout and reorganized around six sections.
- The documentation is published as a site at https://altero.run/, built by Zensical and deployed on every push, a version per release.

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
- Publishing to My Publications the way the desktop client's wizard does, license and all.
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
- Concurrent writes serialized, so one request produces exactly one new version.
- A command line for provisioning, CI, and the documentation to go with it.

[desktop-matrix]: docs/client-compatibility.md#successfully-tested-matrix
[db-req]: docs/deployment.md#database-requirements
[headers]: docs/deployment.md#behind-a-reverse-proxy
[dependencies]: docs/compatibility.md#an-object-that-depends-on-one-the-server-lacks
[parents]: docs/compatibility.md#what-may-be-a-child-of-what
[editing]: docs/web/library.md#editing-an-item
[notes]: docs/web/library.md#writing-a-note
[items]: docs/web/library.md#items
[install]: docs/web-interface.md#installing-it-as-an-app
[source]: docs/deployment.md#from-a-source-checkout
[config]: docs/configuration.md
[1.0.0-beta.5]: https://github.com/eseifert/altero/releases/tag/v1.0.0-beta.5
[1.0.0-beta.4]: https://github.com/eseifert/altero/releases/tag/v1.0.0-beta.4
[1.0.0-beta.3]: https://github.com/eseifert/altero/releases/tag/v1.0.0-beta.3
[1.0.0-beta.2]: https://github.com/eseifert/altero/releases/tag/v1.0.0-beta.2
[1.0.0-beta.1]: https://github.com/eseifert/altero/releases/tag/v1.0.0-beta.1
[1.0.0-alpha.3]: https://github.com/eseifert/altero/releases/tag/v1.0.0-alpha.3
[1.0.0-alpha.2]: https://github.com/eseifert/altero/releases/tag/v1.0.0-alpha.2
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

[@raphaelbahat]: https://github.com/raphaelbahat
[zotero-self-hosted-sync]: https://github.com/raphaelbahat/zotero-self-hosted-sync
[@alpichlabs]: https://github.com/alpichlabs
[@sadgen]: https://github.com/sadgen
[@ScatteredComet]: https://github.com/ScatteredComet
[@mweber0]: https://github.com/mweber0
[@arminbahl]: https://github.com/arminbahl
[PR#7]: https://github.com/eseifert/altero/pull/7
[PR#8]: https://github.com/eseifert/altero/pull/8
[PR#14]: https://github.com/eseifert/altero/pull/14
[Discussion#5]: https://github.com/eseifert/altero/discussions/5
[Discussion#18]: https://github.com/eseifert/altero/discussions/18
[Issue#11]: https://github.com/eseifert/altero/issues/11
[Issue#13]: https://github.com/eseifert/altero/issues/13
[Issue#22]: https://github.com/eseifert/altero/issues/22
[Issue#29]: https://github.com/eseifert/altero/issues/29
[Issue#30]: https://github.com/eseifert/altero/issues/30
