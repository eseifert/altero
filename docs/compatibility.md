# Compatibility notes

altero targets the Zotero desktop application, so where the published
documentation and the official [dataserver](https://github.com/zotero/dataserver)
disagree, the dataserver wins — even when its behaviour looks like a bug. Every
such case is listed here, with the source that settles it.

Three sources are used throughout:

- the live API at `https://api.zotero.org`, compared response by response
- the reference implementation, chiefly `model/API.inc.php`,
  `model/Tags.inc.php` and `model/Items.inc.php`
- read-only requests against a real personal library, which settled the points
  the first two left ambiguous

## Search syntax

`Zotero_API::getSearchParamValues` (`model/API.inc.php`) is the authority for
the `itemType` and `tag` parameters, and it differs from the prose documentation
in two ways that change results.

**Negation covers the whole value.** The leading `-` is stripped before the
value is split on `||`, so `itemType=-book || journalArticle` excludes items of
*either* type. It does not mean "not a book, or a journal article". The
documentation's wording suggests per-alternative negation; the implementation
has none.

This was confirmed by counting against a real library of 442 items: 122
attachments, 12 notes, and `itemType=attachment || note` matching 134. The
negated form `itemType=-attachment || note` returned 308, exactly
`442 - 134`. Per-alternative negation would have returned more than 320.

**`||` only separates when surrounded by whitespace.** The split is
`preg_split("/\s+\|\|\s+/", $val)`. `tag=a||b` is therefore a single tag
literally named `a||b`, and `tag=a ||b` likewise does not split. This is what
lets a tag containing a bare `||` round-trip. Every example in the documentation
uses the spaced form, so clients are unaffected.

A leading hyphen is escaped as `\-`, and only the whole value is stripped —
once, before parsing — so inner spacing in `tag=foo bar || bar` survives.

## Pagination of the sync formats

`Zotero_API::getLimitMax` returns `0` for `format=keys` and `format=versions`,
and their default limit is `0` as well. Zero means *no limit*: both formats
return the entire result set in one response and carry no `Link` header.

This matters more than it looks. The desktop application reads the whole of
`format=versions` to decide what to sync; truncating it to the usual 25 would
not produce an error, it would silently make the client believe the library
contains 25 objects. An explicit `limit` is still honoured for these formats,
and is not capped at 100.

For every other format the maximum stays 100 and the default 25.

## Parameter handling

| Behaviour | Source |
| --- | --- |
| `limit=0` or a negative limit falls back to the default, rather than erroring or clamping to 1 | `parseQueryParams`, `case 'limit'` |
| A limit above the maximum is clamped, not rejected | same |
| `sort=asc` / `sort=desc` is moved to `direction`, keeping the default sort | `parseQueryParams`, `case 'sort'` |
| `qmode` is compared lowercased, so `startsWith` and `startswith` both work | `parseQueryParams`, `case 'qmode'` |
| Any sort field whose name begins with `date` defaults to descending; everything else ascending | `getDefaultDirection` |
| `itemType` may not be repeated | `Zotero_Items::search` |
| `numItems` is a valid sort only for tag endpoints | `parseQueryParams`, `case 'sort'` |
| `extra` and `serverDateModified` are valid item sort fields | same |

## Response shapes

Confirmed against a live library rather than inferred.

**A tag carries no version.** The envelope is `{tag, links, meta}`, with `meta`
holding `type` and `numItems`. Tag versions reach a client through
`format=versions`, not through the object.

**`meta` omits what does not apply.** `creatorSummary` is absent when an item
has no creators, `parsedDate` when it has no date, and both are absent for a
child attachment, whose `meta` is `{}`. `numChildren` is always present.
Summaries are the bare name for one creator, `"Smith and Myers"` for two, and
`"Ranganathan et al."` from three. `parsedDate` emits only the parts present:
`2016`, `2018-05` or `2018-06-20`.

**Error bodies name the object.** A missing item answers `Item does not exist`,
a collection `Collection not found`, a search `Search not found`. An
unrecognised filter value answers `Invalid itemType 'bogus'`, and an
unrecognised sort `Invalid 'sort' value 'bogus'`.

**An unreadable number is ignored, not rejected.** `limit=abc` answers 200 with
the default page size. Only values the server understands and disagrees with,
such as an unknown `sort` field, produce a 400.

**Backward links omit a zero start.** `rel="first"` and `rel="prev"` are written
as `?limit=2`, not `?limit=2&start=0`.

## Fields the published schema does not list

`https://api.zotero.org/schema` gives `attachment` only `title`, `accessDate`
and `url`, and gives `note` and `annotation` no fields at all. All three carry
more than that: an attachment has `linkMode`, `contentType`, `charset`,
`filename`, `md5`, `mtime` and `path`, a note has `note`, and an annotation has
the `annotation*` family. Validating strictly against the published schema
rejects the server's own `/items/new` template.

Those sets are therefore declared in `UNLISTED_FIELDS` in
`services/itemwrites.py`. The attachment set was read off live responses, the
annotation set from the client's data model. A field outside both the schema and
that table is still rejected, so a storage field on a `book` is an error.

If a write is refused with `Invalid field`, this is the first place to look.

## Timestamps

`dateAdded` and `dateModified` come from the client and round-trip unchanged, so
uploading an existing library keeps its history instead of rewriting every item
to the moment of upload. `serverDateModified` is always the server's own, which
is what makes sorting by it trustworthy: a client cannot reorder another
client's results by backdating its own timestamps.

## Citations and bibliographies

Upstream has no citation code of its own: `Zotero_Cite` posts CSL JSON to a
citation server running citeproc-js and re-styles the HTML that comes back
(`model/Cite.inc.php`). altero does the same two steps in process, with
[citeproc-py](https://github.com/brechtm/citeproc-py) as the processor and
[citeproc-py-styles](https://github.com/inveniosoftware/citeproc-py-styles) — a
packaged copy of the Citation Style Language repository — as the style source.
Nothing is fetched at request time, so an instance with no outbound network
renders in any published style.

**The CSL mapping is the schema's, not ours.** `https://api.zotero.org/schema`
carries the `csl` tables Zotero itself maps with: item type to CSL type,
CSL variable to the item fields that may supply it, creator type to CSL name
variable. `altero/cite/csljson.py` applies them in the order
`Zotero_Cite::retrieveItem` does — first field with a value wins, the item
type's primary creator becomes `author` whatever it is called, enclosing quotes
are stripped — so a schema update moves the output with it.

**`format=csljson` wraps one item the same way it wraps many.** A single item
comes back as `{"items": [ ... ]}` rather than as the object itself. Upstream's
`ItemsController` carries a commented-out line saying it would return the bare
object in a later API version; until it does, the wrapper is what clients parse.

**`format=bib` is one document.** It carries `Total-Results` but no `Link`
header, and rejects `sort`, `direction`, `start`, `limit` and `order` with a
400 — a bibliography is not a page of results. Its maximum and default page
size are both 150 (`Zotero_API::MAX_BIBLIOGRAPHY_ITEMS`).

**`include` is validated rather than ignored.** `data`, `bib`, `citation`,
`csljson`, `bibtex`, `biblatex`, `ris` and `none` are accepted; `include=none`
may not be combined with anything; `include` outside `format=json` is a 400, as
is an unknown value. Upstream additionally accepts `html`, which needs Atom, and
eleven more export formats; those are refused here rather than accepted — a
client that asked for one and silently received `data` would have no way to
notice.

**Three export formats are written, not fourteen.** Upstream produces them by
handing the item JSON to a translation server running Zotero's own JavaScript
translators. altero has no such thing, so `bibtex`, `biblatex` and `ris` are
mapped from the CSL JSON an item already renders as, with
[bibtexparser](https://github.com/sciunto-org/python-bibtexparser) and
[rispy](https://github.com/MrTango/rispy) doing the writing. Consequences worth
knowing:

- CSL is a superset of what these formats carry, so the mapping loses nothing
  they can hold — but a type CSL renders as `document` becomes `@misc` or `GEN`,
  where a translator might have known better.
- Citation keys are generated as `surname` + `year` + first significant title
  word, disambiguated with a letter within one response. Upstream's translator
  has its own scheme; neither is stable across servers, which is why a
  `citationKey` field in the item wins over both.
- Tags become `keywords`. They are not part of CSL, so they are carried
  alongside it rather than through it.
- `bookmarks`, `coins`, `csv`, `endnote_xml`, `evernote`, `mods`, `refer`,
  `refworks_tagged`, `rdf_*`, `tei` and `wikipedia` are not implemented, and are
  refused rather than silently answered as JSON.

Four places where the rendered output is not upstream's:

- **Style names are resolved through the CSL project's own
  `renamed-styles.json`.** The API's default, `chicago-note-bibliography`, was
  renamed years ago; the alias file maps it, and 609 others, onto what the
  repository ships now. An unknown style answers `404 Style not found`.
- **A style given as a URL is refused with `400 Invalid style`.** Upstream's
  citation server fetches it. Fetching arbitrary URLs would make the server a
  proxy for whoever holds an API key.
- **The wrapper markup is reproduced, not the layout arithmetic.** Line height,
  hanging indent and entry spacing are read from the style and written as inline
  CSS exactly as the client's `makeFormattedBibliography` does. The
  `second-field-align` handling, which needs citeproc-js's `maxoffset`, is not:
  citeproc-py does not emit the `csl-left-margin` structure it applies to.
- **A doubled full stop is collapsed.** An initialled name ends in a period and
  the style adds its own; citeproc-js drops one, citeproc-py emits both, and
  every name would otherwise read `Doe, J..`. Only text outside tags is touched,
  and three periods are left alone.

One limitation is worth knowing about. citeproc-py's support for the most
intricate styles is not complete, and the in-text citation of
`chicago-shortened-notes-bibliography` — which is what the API's default style
name now resolves to — renders a stray `edition` term for an item that has no
locator. Its bibliography is correct, as are the citations of every other style
tried (APA, MLA, IEEE, Nature, AMA, the other Chicago variants). The bibliography
is the path both the API and the interface lead with.

One correction is applied to citeproc-py itself, in `altero/cite/compat.py`:
`citation-number` is excluded there from what counts as calling a variable, so a
numeric style whose citation groups the number with a locator macro — IEEE —
renders an empty citation. CSL 1.0.1 counts it as a number variable.
`tests/test_citations.py` covers it, so a release that fixes it upstream shows
up as a failing test.

## Item type schema

These came out of comparing all 163 schema responses against the live API.

**`/itemTypes` and `/itemFields` are ordered by localized name**, not by
identifier, so the order changes with `locale`. Sorting is by code point, which
is why `Software` (`computerProgram`) sorts under S and `TV Broadcast` precedes
`Thesis`.

**`/itemTypeCreatorTypes` pins the primary type first** and sorts the remainder
by localized name — again per locale, so the German ordering differs from the
English one.

**`/itemFields` omits base-only fields.** Names such as `medium` and `authority`
appear only as the `baseField` of another field and are not listed, though they
remain valid in writes.

**Templates disagree with the schema for two item types.** The schema marks
`creator` as the primary creator type for `videoRecording` and `radioBroadcast`,
and `/itemTypeCreatorTypes` reports it as such, yet `/items/new` seeds those
templates with `director`. Both behaviours are reproduced, so a template fetched
from altero is interchangeable with one fetched from Zotero. See
`TEMPLATE_CREATOR_TYPES` in `altero/itemschema/registry.py`.

## The file protocol

Uploading a file is three requests — authorize, send the bytes, register — and
altero speaks the same exchange, including the `uploadKey` carried between the
steps and the `{"exists": 1}` reply when the server already holds those bytes.

The middle step differs of necessity. Upstream returns an S3 URL together with a
`prefix` and `suffix` that the client wraps around the file to form a multipart
POST. A self-hosted server has no S3, so the authorization step points back at
altero and both are empty strings, meaning the client sends the file with
nothing wrapped around it. A client that concatenates prefix, file and suffix as
documented still produces exactly the file.

Uploaded bytes are checked against the declared MD5 and length before being
stored, and `If-Match` or `If-None-Match` is required, so a client working from
stale information cannot overwrite a newer file.

## Obtaining a key

The desktop client asks for `POST /keys/sessions`, opens the `loginURL` it gets
back in a browser, and polls `GET /keys/sessions/<token>` until the response
carries `apiKey`, `userID` and `username`. It keeps polling while the status is
`pending`.

An earlier version of this note claimed the client *refuses* a completed
session missing any of those three. That is unverified and probably too strong.
Reading `syncAPIClient.js`, `checkLoginSession` inspects only the HTTP status,
and the caller in `preferences_account.jsx` branches only on `result.status`.
What the caller then does is

    checkUser(window, result.userID, result.username, result.displayName, result.emails)

so a missing field would surface inside `checkUser` rather than as an explicit
refusal. altero sends all of them regardless, so the distinction does not
affect it — but the claim should not be read as established.

That call is also where two omissions were found. The client passes
`displayName` and `emails` on to `checkUser`, and altero was sending neither;
`/keys/current` likewise carries `emails`, which
`displayFields(keyInfo.username, { emails: keyInfo.emails })` reads. Both are
now sent. Neither appears anywhere in the published documentation — only in the
client source — which is the same pattern as the rest of this file.

**Usernames and email addresses are separate, as they are upstream.** The
client's own model has one username, one display name and a *list* of
addresses, so altero keeps a username and adds an address beside it rather than
using the address as the identifier. A username may not contain `@`: sign-in
accepts either, and picks which column to search from the shape of what was
typed, so a username holding an `@` could otherwise name somebody else's
address and leave one of the two accounts unreachable. altero holds at most one
address per account and only reports it once it has been confirmed, so `emails`
is either empty or a single entry.

Changing a username is safe for a linked client, which is worth recording
because it is not obvious: identity is the numeric `userID`. `checkUser` warns,
offers to reset the data directory and quits only when the *userID* differs; a
changed username alone is absorbed with `setCurrentUsername(username)` and no
prompt.

Upstream authenticates the user against zotero.org in that browser window.
altero sends that window to its own interface: `loginURL` answers `303` to
`/app/link?token=…`, which asks the signed-in user to confirm and then issues
the key. The exchange the client sees is unchanged — it opens a URL and polls,
exactly as before.

The concern that kept this at the command line for a while is answered rather
than dropped. What is handed over is a full-access key that outlives the
browser session, which is a larger grant than signing in to read one's own
library, so it is not something a signed-in tab should be able to do merely by
being pointed at a URL. Confirming therefore takes the password again, the way
every other credential change in the account does; the CSRF token stops the
form being submitted from another origin, and the password stops a prepared
link being worth sending to somebody.

The command line still works and is still the way in when the interface has not
been built — `loginURL` then serves the `altero login approve` instructions as
it always did, because the API is entirely usable in that state and redirecting
to a 503 would be worse than a sentence somebody can act on.

**A session that names an account is refused for any other.** The client sends
`{"userID": …}` when it is re-authenticating, and handing it a key belonging to
somebody else is not a cosmetic mismatch: `checkUser` sees a changed `userID`,
warns, offers to reset the data directory and quits. The confirmation screen is
told this before it offers a button, and the endpoint refuses it again if the
request is made anyway.

**The key it issues covers group libraries.** Upstream's
`createAPIKeyFromCredentials` asks for `{library, notes, write, files}` on the
user and full access to groups, and a client key without groups presents as a
server that has lost them. `altero login approve` grants the same, so the two
paths agree.

`POST /keys`, which creates a key from a username and password, is not
implemented. The client only reaches it when migrating a profile that still
holds a pre-2016 sync password.

**Key management is not missing from the v3 API; it was never in it.**
`/users/<id>/keys` looks like an API for listing, creating and revoking keys,
but `KeysController` gates all of it on
`$isWebsite = $isSuper || ($this->apiVersion >= 3 && $this->cookieAuth && …)`:
an API key alone gets a 403, and the paths exist for zotero.org's own signed-in
pages. altero has the same thing under `/web/account/keys`, reached with the
same kind of credential — a session cookie — plus `altero key add` and
`altero key revoke` for an operator. What an API key can do to itself is what
upstream lets it do: read `/keys/current` and delete it.

## What the desktop client actually sends

Two of these were found by running the real client, not by reading the
documentation, and neither is described there.

**`mtime` is milliseconds, and needs 64 bits.** The client sends an
attachment's modification time as milliseconds since the epoch, which has not
fitted in a signed 32-bit integer since January 1970. In a column typed
INTEGER, SQLite takes it — its INTEGER is 64-bit — and PostgreSQL refuses it
with `value out of int32 range`. File uploads therefore worked in development
and failed against every container deployment, with the whole suite green.
`storage_uploads.mtime` is BIGINT, and `tests/test_web_on_postgres.py` covers
it against the database the image actually uses.

**Full text is uploaded in batches.** The documented endpoints are
`GET`/`PUT` on `<prefix>/items/<key>/fulltext`, but the client uploads with
`POST <prefix>/fulltext`, carrying an array of
`{key, content, indexedChars, totalChars, indexedPages, totalPages}` and
requiring `If-Unmodified-Since-Version`. The reply is the usual multi-object
report. Every entry of `successful` and `unchanged` must be an object with a
`key`, because the client reads `results[state][index].key`; a bare key string
leaves it looking up an item by `undefined`.

Upstream advances the library version once per item in this batch. altero keeps
its one-version-per-request rule, which the client cannot tell apart: it uses
only the final `Last-Modified-Version` as a watermark.

**Tag deletions arrive with no tag named.** The client builds them as
`tags=a||b` — plural, and joined with a bare `||` rather than the spaced form
the search syntax uses. Its own parameter filter then drops the name, because
`queryParamOptions` in `syncAPIClient.js` lists `tag` and not `tags`, so the
request reaches the server as a bare `DELETE <prefix>/tags`.

Upstream answers `204` having deleted nothing, and the client accepts only `204`
or `412` here, so rejecting the request aborts the sync. altero therefore
answers `204` as well, and additionally understands `tags` with bare `||`
separators should the client ever stop dropping it.

**Uploads are compressed.** The client gzips the full-text batch and announces
it with `Content-Encoding: gzip`. Nothing in the documented request format
mentions this, and a server that reads the body as UTF-8 fails on the second
byte of the gzip magic number. Bodies are therefore decompressed before anything
else looks at them, and a body that does not decompress is a `400` rather than
an unhandled failure.

**A snapshot is uploaded as a ZIP, and the digests differ.** When the connector
saves a page, the client zips the attachment directory and sends `zipMD5` and
`zipFilename` alongside the usual parameters. In that case `md5` describes the
*original* file while the bytes on the wire are the archive, and `filesize` is
the archive's size. Validating the transfer against `md5` rejects every snapshot.
altero checks against `zipMD5` when present and records `md5` on the item, which
is what the client sends back as `If-Match` next time.

**The upload URL must be absolute.** The client passes it straight to
`XMLHttpRequest.open()`, which rejects a bare path with "is not a valid URL".
Upstream returns an S3 URL, so this only shows up on a server that hosts its own
uploads.

**Uploads are diffs, not whole objects.** Once an item has been synced, the
client keeps the server's version of it in a local cache and later uploads only
what changed — `{key, version, lastRead, dateModified}` and nothing else, with
no `itemType`. Upstream calls this a partial update: `validateJSONItem` clears
its required-property list and takes the item type from the stored item.

An object in a `POST` batch is therefore treated as a partial update when it
names an item that exists and omits `itemType`, leaving every property it does
not mention alone. A new item still has to say what type it is. Requiring
`itemType` unconditionally rejects the diff, and the client answers by giving up
with "Made no progress during upload".

`lastRead` is a real attachment field, added at schema version 42, which the
client sets on its own when a snapshot is opened.

**Registering a finished file upload bumps the library version**, so the
full-text upload that follows it can arrive with a stale
`If-Unmodified-Since-Version` and be answered 412. The client notices, resyncs
and repeats the upload successfully — one wasted round trip, not a failure.
This is upstream's behaviour as well: `Zotero_Storage::updateFileItemInfo` calls
`Zotero_Libraries::updateVersionAndTimestamp` before saving the item. Suppressing
the bump to avoid the 412 would break `?since=` for anyone tracking file changes.

**The client's library version may only ever go up.** A precondition ahead of
the library is not a conflict: `Zotero_Libraries::updateVersionAndTimestamp`
bumps the counter with `WHERE libraryID=? AND version <= ?` and answers 412 only
when that matches no row, so `If-Unmodified-Since-Version: 29` against a library
at version 0 is accepted and the write is stamped 1. altero does the same, in
`check_library_version`.

Upstream can never reach that state, because a shard's counter moves forward for
the life of the database. altero can: recreating the database restarts the
counter at zero while a client keeps the version it last saw. What follows was
observed, not inferred — the client rejects the response with
`_libraryStorageVersion cannot decrease`, rolls back the transaction that would
have marked the objects synced, and re-uploads the same objects on every
subsequent sync, each attempt writing them again and advancing the server by one.

**A client in that state cannot be reset out of it either.** "Restore to server"
zeroes the local object versions, reads `format=versions` from the server, and
then assigns the server's library version to its own — which is the same
decrease, and fails in `_restoreToServer` with `_libraryVersion cannot decrease`.
Both directions are therefore closed from the client side; the only way back is
to raise the server's counter above what the client remembers, which is what
`altero library set-version` is for. Objects the client believes it already
synced are not re-uploaded afterwards, so a library restored this way can be
missing everything written before the reset.

Neither the precondition nor the response is changed to work around this: both
are upstream's. See `TestAVersionAheadOfTheLibraryIsAccepted` in
`tests/test_compatibility.py`.

**The client asks for two things the data server does not provide.** Grepping
the dataserver source for `retraction`, case-insensitively and across every PHP
file, returns nothing, and there is no WebSocket route either. Both are served
by something else behind `api.zotero.org`, so neither has a reference
implementation to copy or a documented response shape.

`GET /retractions/list` is polled to flag retracted papers. altero answers `404`.
An empty list would be the easy way to silence the client's log entry, but it
asserts that nothing in the library has been retracted, which altero has no
basis to claim; `404` says the service is not here, which is true. The client
logs the failure and syncs normally.

**The streaming API is not covered by `api.url`, and the key goes to
zotero.org.** This one is a configuration hazard rather than a compatibility
question, and it was found by chasing a stray log line:
`WebSocket connection closed: 4403 Invalid API key`.

The [documented][streaming] endpoint is `wss://stream.zotero.org` — a fixed
host, not a path under the API base — and 4403 is its code for an invalid key.
The client resolves the address as

    let url = this.url || Zotero.Prefs.get('streaming.url') || ZOTERO_CONFIG.STREAMING_URL

with `ZOTERO_CONFIG.STREAMING_URL` compiled in as `wss://stream.zotero.org`
(both read out of `omni.ja` in a 9.0.6 installation). Redirecting `api.url`
therefore does nothing here: unless `extensions.zotero.streaming.url` is also
set, the client opens a socket to zotero.org and sends it an API key by
`createSubscriptions`. The key is rejected as unknown, but it has been
transmitted — a credential granting full access to a private library, handed to
a third party, by a deployment whose purpose is that the data stays put.

`extensions.zotero.streaming.enabled = false` stops it, and `README.md` now
lists that alongside `api.url` as part of pointing a client at altero.

The same finding makes streaming worth implementing eventually: because
`streaming.url` exists, a client can be pointed at an altero socket rather than
merely stopped from reaching zotero.org.

[streaming]: https://www.zotero.org/support/dev/web_api/v3/streaming_api

## API versions

Only version 3 is served. A request naming another version through the
`Zotero-API-Version` header or the `v` parameter is refused with `400` rather
than answered, because a v1 or v2 client expects Atom, which is not implemented:
returning v3 bodies under a v2 label would be worse than saying so. A header and
a parameter that disagree are also refused, as upstream does.

## The `relations` map

`Zotero_DataObject::getRelations` builds the map from stored predicate-object
pairs: the first object for a predicate is emitted as a **string**, and a second
one turns the value into an **array**. Zotero relies on that — related items are
`dc:relation` naming several other items — so the shape is not cosmetic.

altero stored item relations correctly and then rendered them with a dict
comprehension keyed on the predicate, which kept only the last object. An item
related to three others came back related to one, and the client then held the
truncated map as the truth. Both types now go through `render_relations`.

**Collections have relations too**, and altero accepted and dropped them: the
write path never read the property and the serializer returned `{}`
unconditionally. They are stored now, in `collection_relations`, shaped like
`item_relations` so that a predicate can name more than one collection.

An empty *array* is accepted in place of an empty object, which upstream allows
in as many words — "Allow an empty array, because it's annoying for some clients
otherwise". Rejecting it would fail the whole object.

Not copied: upstream restricts predicates to an allow-list
(`Zotero_Relations::$allowedCollectionPredicates` is `owl:sameAs` and
`mendeleyDB:remoteFolderUUID`; items get a longer one) and requires Zotero URIs
as values for the non-external ones. altero enforces neither, for items or
collections, so it accepts relations that api.zotero.org would refuse. That is
the permissive direction, so no client is broken by it, but a library moved from
altero to zotero.org could carry a relation that upstream rejects.

## Backoff and Retry-After

Both headers must be **whole seconds** or the client discards them.
`Zotero.Sync.APIClient._checkRetry` logs "Invalid Retry-After delay" and returns
false unless `parseInt(retryAfter) == retryAfter`, and the `Backoff` handler
guards the same way before calling `this.caller.pause(backoff * 1000)`. A value
of `0` is as bad as a fractional one: it is a pause of no time at all, followed
by the same refusal.

`_check429` prefers `Retry-After` and falls back to its own increasing delays
when the header is missing, so a bare 429 is understood too -- but it makes the
client guess.

altero refuses with 429 and a whole-second `Retry-After`, never below 1. It does
not send `Backoff`: that header asks a client to slow down while the server is
still answering, which needs a load signal this server does not have.

## My Publications

`/users/<id>/publications/items` is read **without a key** — upstream's own test
file sets `API::useAPIKey("")` for every case in it and expects 200. Only items
flagged `inPublications` are visible, through `items`, `items/top` and
`items/<key>`; a key that is not published answers 404 rather than 403, since
hiding an item from the listing is pointless if its key still fetches it.

`publications/collections` and `publications/searches` answer 404 upstream, and
do here. Writes are refused: items reach the list by being written to the
library with `inPublications` set, not by being posted here.

There is no group form. My Publications belongs to a person, which is the same
reason `inPublications` is refused on a group item.

`publications/settings` and `publications/deleted` are served, because the
client polls both as part of the same cycle it runs for any library and treats
anything but a 200 as a failed sync. Both are empty: settings answers `[]` with
`Total-Results: 0`, deletions answer `{}`, each carrying the library's version.
That is what upstream's `ApiController` returns for them.

Its one further branch is not copied. `publications/settings` answers **400**
there — "Please upgrade to the latest Zotero 5.0 beta" — as soon as the user
has any published item, under a comment reading `TEMP: Remove after integrated
publications upgrade`. It exists to stop an old client syncing a *legacy*
publications library, a separate library that altero has never had and cannot
create. Reproducing it would mean refusing every modern client that has
published anything, with advice it has already followed.

## Trashing a collection or a saved search

Zotero trashes these by setting `deleted` on the object, not by deleting it, and
syncs the flag like any other property —
`if (isset($json->deleted) || !$partialUpdate) { $collection->deleted = ... }`
in `Zotero_Collections::updateFromJSON`, and the same in `Searches`. altero
could report the flag but never set it, so a collection the user moved to the
trash stayed untrashed on the server and in every other client.

**Trashed collections and searches stay in the listings**, carrying
`deleted: 1`. Upstream has no trash filter in its collection or search queries,
and the client has no `includeTrashed` parameter for either — it sends a bare
`GET <prefix>/collections?format=versions`. A listing that hid them would
therefore not say "trashed", it would say "gone".

Their child counts follow upstream exactly, and the two differ:

| Count | Upstream | Trashed children counted |
| --- | --- | --- |
| `numCollections` | `SELECT COUNT(*) FROM collections WHERE parentCollectionID=?` | yes |
| `numItems` | joins `deletedItems` and requires `DI.itemID IS NULL` | no |

Items are unaffected throughout. They are the one type with real trash
semantics upstream — their own endpoint and an `includeTrashed` parameter — and
`/items` still hides them.

The value must be a boolean or the integers 0 or 1, as upstream requires;
without that check a string `"false"` would read as trashed.

## `inPublications`

An ordinary item property upstream, and one altero used to reject outright with
"Invalid field" — a per-item `400` for anything the user had put in My
Publications, and a client answers that by sending the item again on every sync
rather than giving up.

`Zotero_Items::validateJSONItem` attaches three refusals to it, and only to a
value that is true; a falsy one is accepted with no further questions, including
in a group library.

| Refused | Message |
| --- | --- |
| A group library | `Group items cannot be added to My Publications` |
| A top-level note or attachment | `Top-level notes and attachments cannot be added to My Publications` |
| A `linked_file` attachment | `Linked-file attachments cannot be added to My Publications` |

A *child* note or attachment is allowed: that is what My Publications is for. A
linked file is not, because the server does not hold its bytes and so could not
publish them.

It is emitted only when true, the way `deleted` is
(`if ($this->getPublications()) $arr['inPublications'] = true;`), rather than
put on every item in every library as `false`.

The `/publications` endpoints — the public listing of those items — are still
not implemented. The property is what the sync path needs.

## Objects that were sent again without changing

An object identical to the stored one is reported under `unchanged` and keeps
its version, as upstream does: `Zotero_DataObjects::updateMultipleFromJSON`
calls `addUnchanged` when `updateFromJSON` reports no change. Writing it again
would be visible library-wide — the library version advances, and every *other*
client re-downloads an object that never changed.

What counts as a change is everything a client can set: the item type, the
fields, the creators in order, the relations, the parent, the trash flag, the
client's own `dateAdded` and `dateModified`, and the tags and collections, which
live in link tables and so are read before those rows are rewritten. The version
and `serverDateModified` are excluded, being the server's own; the sort keys are
excluded as well, since they are derived from the fields.

Finding out costs applying the payload, which stamps a version on the way. The
multi-object path already gives each object its own savepoint, so an unchanged
object is discarded by rolling that back — the same mechanism a rejected object
uses. A batch in which nothing changed leaves the library version where it was,
because nothing succeeded and the whole request rolls back.

Two places deliberately do not do this. A key-based `PUT` or `PATCH` has no
report to put the answer in, and upstream's controller ignores the flag there
too. The full-text batch is a different upstream code path (`Zotero_FullText`)
and is left alone.

## Deliberate differences

Five places where altero does not copy upstream:

- **Group creation and membership stay on the command line.** Upstream serves
  `POST /groups` and `POST /groups/<id>/users`, but neither is part of the API a
  client uses: both require `$this->permissions->isSuper()`, which
  `ApiController` grants only to an operator authenticating out of band rather
  than with an API key, and both take an **XML** body parsed with
  `new SimpleXMLElement($this->body)`. It is zotero.org's own administrative
  back door.

  Reproducing it would mean inventing a superuser credential altero does not
  have and exposing a privileged write path on a self-hosted server, to offer
  something `altero group add` and `altero group member` already do at the same
  trust level without listening on a socket. The Zotero client never calls it.

- **`alternate` links are omitted.** Every upstream envelope carries a link to
  the corresponding page on zotero.org, and the `Link` header always ends with
  `rel="alternate"`. Pointing at zotero.org would send clients to someone
  else's copy of the data, and altero's own interface is not a per-object
  permalink scheme, so `library.links` is empty and object envelopes carry only
  `self` and `up`. A consequence is that a
  single-page response has no `Link` header at all, where upstream still emits
  the `alternate` one.
- **An unknown `locale` falls back to `en-US`.** The live API answers `500`.
- **Rate limiting is off unless configured.** Upstream always throttles with
  `Backoff` and `Retry-After`; a self-hosted server with a handful of clients
  has nothing to protect itself from, so the limiter is present but disabled
  until `ALTERO_RATE_LIMIT` names an allowance.
- **Fields sharing a localized name may order differently.** Three fields are
  called "Format"; upstream breaks the tie on an internal identifier that the
  published schema does not contain, so their relative order is arbitrary here.
