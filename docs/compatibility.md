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
carries `apiKey`, `userID` and `username`. It refuses a completed session
missing any of the three, and keeps polling while the status is `pending`.

Upstream authenticates the user against zotero.org in that browser window.
altero has no web interface and stores no passwords — accounts and keys are
provisioned from the command line — so the page it serves at `loginURL` explains
how to approve the login there instead, and `altero login approve` completes the
session. The exchange the client sees is unchanged.

`POST /keys`, which creates a key from a username and password, is not
implemented. The client only reaches it when migrating a profile that still
holds a pre-2016 sync password.

## What the desktop client actually sends

Two of these were found by running the real client, not by reading the
documentation, and neither is described there.

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

## Known gap: nothing is ever reported unchanged

The multi-object report has four sections, and altero fills three. Upstream
compares an incoming object with the stored one and, when they match, reports it
under `unchanged` and leaves its version alone. altero writes it again and
stamps a new version: `WriteResults.add_unchanged` exists because the response
format requires the key, but it has no callers, so `unchanged` is always `{}`.

The cost is churn rather than breakage. A client that re-sends what it already
holds is told the object was written, and the library version it gets back is
new, so every *other* client re-downloads an object that did not change. The
client this was found against uploads diffs, which keeps it rare -- but a
retried batch, or any client that uploads whole objects, pays it every time.

`test_resending_an_identical_object_rewrites_it` in `tests/test_sync_cycle.py`
pins the current behaviour so that implementing the comparison fails loudly and
this section gets rewritten.

## Deliberate differences

Four places where altero does not copy upstream:

- **`alternate` links are omitted.** Every upstream envelope carries a link to
  the corresponding page on zotero.org, and the `Link` header always ends with
  `rel="alternate"`. altero has no web interface, and pointing at zotero.org
  would send clients to someone else's copy of the data, so `library.links` is
  empty and object envelopes carry only `self` and `up`. A consequence is that a
  single-page response has no `Link` header at all, where upstream still emits
  the `alternate` one.
- **An unknown `locale` falls back to `en-US`.** The live API answers `500`.
- **Rate limiting is absent.** Upstream throttles with `Backoff` and
  `Retry-After`; a self-hosted server with a handful of clients has nothing to
  protect itself from. The headers are named in the CORS configuration so that
  adding them later needs no client change.
- **Fields sharing a localized name may order differently.** Three fields are
  called "Format"; upstream breaks the tie on an internal identifier that the
  published schema does not contain, so their relative order is arbitrary here.
