# What works

The v3 API surface altero serves, what it does not serve yet, and the two
things the desktop client asks for that no data server documents.

## Implemented

- Authentication by `Zotero-API-Key` header, bearer token or `key` parameter,
  with per-library and per-group permissions
- `/keys/<key>` and `/users/<userID>/groups`
- The schema endpoints (`/itemTypes`, `/itemFields`, `/itemTypeFields`,
  `/itemTypeCreatorTypes`, `/creatorFields`, `/items/new`, `/schema`)
- Reading items, collections, saved searches and tags, including `format=json`,
  `atom`, `keys` and `versions`, pagination with the `Link` header, sorting,
  `since`, and `If-Modified-Since-Version`
- Atom feeds and entries, with `content` choosing the body: `html`, `json`,
  `bib`, `citation`, `csljson`, the export formats, `none`, or several at once
- Tag listings scoped to a library, a collection, one item, the top level or
  the trash
- Writing items, collections and saved searches, and deleting tags, with the
  multi-object response, version preconditions and `Zotero-Write-Token`
- Recognising an object re-sent unchanged, so it keeps its version and the
  library's does not move
- `inPublications`, the My Publications flag, with the refusals upstream
  attaches to it
- Trashing collections and saved searches, which sync as a `deleted` flag on
  the object rather than as a deletion
- `relations` on both items and collections, including a predicate that names
  several objects
- `/users/<id>/publications/items`, `settings` and `deleted`, readable without
  a key
- Rate limiting, off unless configured, answering `429` with `Retry-After`
- Citations and bibliographies: `format=bib`, `format=csljson` and
  `include=bib,citation,csljson`, in any of the styles published by the
  [CSL project](https://github.com/citation-style-language/styles), with
  `style`, `locale` and `linkwrap`. Nothing is fetched at request time
- Export as `format=bibtex`, `biblatex` or `ris`, and the matching `include`
  values, with tags carried across as keywords
- Items of every type, including notes, attachments and annotations, whose
  fields the published schema does not list
- Client-supplied `dateAdded` and `dateModified`, kept as sent
- `/deleted?since=`, so a client that has been away can tell a deletion from an
  object it has not fetched
- Library settings, and attachment full-text, including the batch upload the
  desktop client uses
- The attachment file protocol, storing files once per digest
- The streaming API, at `/stream`: a client pointed at it with
  `extensions.zotero.streaming.url` is told the moment a library changes
  instead of waiting for its next poll
- Provisioning from the command line, CORS, and API version negotiation

## Not implemented

- The eleven export formats beyond BibTeX, BibLaTeX and RIS
- Group creation through the API — [the command line does
  it](administration.md)
- Full-text **search**. The text a client uploads is stored, versioned and
  served back, but `q` with `qmode=everything` covers an item's own fields, so
  text from an attachment cannot be found through it

The web interface has its own list of what is and is not built; see
[web-interface.md](web-interface.md).

## Two things the client asks for that no data server documents

`GET /retractions/list`, which the desktop client polls to flag retracted
papers, and the streaming API it opens a WebSocket to, appear nowhere in the
dataserver source. There is no reference implementation to copy for either.

altero answers the first with `404` rather than an empty list, which would
assert that nothing in the library has been retracted. The client logs the
failure and syncs normally.

The streaming API *is* documented, so it is implemented — from the published
protocol, with the handful of inferred details marked as such in
[compatibility.md](compatibility.md). It is reached at a compiled-in
`wss://stream.zotero.org` unless `extensions.zotero.streaming.url` is set,
which is why [connecting a client](clients.md) now sets that preference: left
alone, the client hands an API key to zotero.org.

## One version per request

Writes to a library are serialized, so one request produces exactly one new
version however many objects it touches. See
[schema.md](schema.md#concurrency) for how, and for what happens without it.
