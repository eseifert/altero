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

## API versions

Only version 3 is served. A request naming another version through the
`Zotero-API-Version` header or the `v` parameter is refused with `400` rather
than answered, because a v1 or v2 client expects Atom, which is not implemented:
returning v3 bodies under a v2 label would be worse than saying so. A header and
a parameter that disagree are also refused, as upstream does.

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
