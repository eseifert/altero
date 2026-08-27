# Compatibility reference

This document records Zotero behavior that altero must reproduce even when the public API documentation is incomplete, ambiguous or different from the reference server.

## How to use this reference

altero targets the unmodified Zotero Desktop application. At the protocol boundary, the practical rule is:

> When published documentation and the behavior required by the real client disagree, compatibility with the real service wins.

The evidence used here comes from three places:

- the live API at `https://api.zotero.org`, compared response by response;
- the official dataserver implementation; and
- read-only requests and observed exchanges from real Zotero libraries and clients where the first two sources are incomplete.

Each section explains a concrete behavior, why altero implements it that way, and—where relevant—how altero deliberately differs.

## API queries and response behavior

### Search syntax

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

### Quick search and full-text search

`q` is a different parameter from the two above and parses by different rules:
`Zotero_Utilities::parseSearchString` splits it, and `Zotero_Items::search`
(`model/Items.inc.php`) turns the parts into SQL.

**The parts are AND-ed, the fields OR-ed.** Upstream emits one `AND (...)` per
part, and inside it ORs the title, the note title, the creator names and the
year together. `q=call me` therefore wants both words and not the phrase. A
double-quoted phrase stays one part, so `q="call me"` does want the phrase.
Single quotes are stripped where they touch whitespace or an end of the string,
which means they never group.

**`q=0` matches everything.** The parser drops any part PHP considers falsy —
`if (!$part) continue` — and the test runs on the token before its quotes come
off. An unquoted `0` is falsy, so it contributes no part; a query of nothing but
`0` leaves no clause at all and the listing is unfiltered. `q="0"` is quoted,
truthy, and searches for it. Copied rather than corrected.

**`qmode=everything` adds the attachments' text.** For each part, upstream asks
Elasticsearch for the item keys whose stored content matches
(`Zotero_FullText::searchInLibrary`) and ORs `I.key IN (...)` into that part's
clause. The keys are the attachments' own, so in `/items` the attachment is what
matches, not the item it hangs under.

altero has no Elasticsearch and will not acquire one — a search cluster is
exactly the operational dependency `motivation.md` rules out — so it matches the
stored text with `LIKE` instead. Three differences follow, and only the first is
a narrowing:

- **Characters rather than tokens.** The index maps `content` as a plain `text`
  field (`misc/elasticsearch/item_fulltext/mapping.json`), so it gets the
  standard analyser: tokenised and lowercased, but *not* stemmed and not accent-
  folded. `match_phrase_prefix` then matches whole tokens with the last one as a
  prefix. altero matches the characters instead, which cuts both ways. It finds
  what upstream would not — `q=equod` reaches *Pequod* — and misses a phrase
  upstream would join across punctuation, since `q="Pequod sailed"` is looking
  for exactly that and the text reads `Pequod, sailed`. Neither implementation
  stems, so `q=sailing` reaches *sailed* in neither.

  **Accents are not folded, and CJK matches as a phrase.** `q=cafe` does not
  reach *café*, on either backend. Neither does upstream's: the mapping carries
  no `asciifolding` filter, so the standard analyser lowercases and stops there.
  Zotero 9 made the *client's* search accent-insensitive, but that is the copy
  it holds locally; the same query against api.zotero.org is as accent-sensitive
  as this one, so the mismatch a user sees is the ecosystem's rather than
  altero's. CJK needs nothing: matching characters means `量子計算` requires
  those four adjacent and `計算量子` does not match, which is the phrase
  behaviour the client had to be fixed to produce. Both are pinned in
  `test_fulltext.py::TestSearching`. The analyser's composition is read from
  Elasticsearch's documented default rather than observed — no instance was run.

  Case-insensitivity comes from `ILIKE` on PostgreSQL and from
  `lower(content) LIKE lower(?)` on SQLite, which SQLAlchemy emits because
  SQLite has no `ILIKE`. **Case folding outside ASCII is therefore not a
  property altero has.** It depends on how the SQLite in use was built:
  `lower()` is ASCII-only unless compiled with ICU. `Übung` matches `übung` on
  a Gentoo build of SQLite 3.53.1 with ICU and does not on the SQLite that
  GitHub Actions runs, which is where a test asserting it failed. altero does
  nothing to make the two agree, so nothing should be built on either answer;
  `test_fulltext.py` pins only ASCII case folding, which holds everywhere.
- **No 300-result cap.** Upstream asks Elasticsearch for `'size' => 300` and
  silently drops the rest, so a library where 400 PDFs mention a word answers
  for 300 of them and gives no sign of it. altero has no cap. This is a
  deliberate divergence: the number is an artefact of how upstream fetches its
  hits rather than a rule about what the API means, and copying it would mean
  discarding matches on purpose.
- **`qmode=everything` also searches the item's other fields.** Upstream reaches
  the title, creators and year and then only the attachment text, so a match on
  `publisher` is altero's alone. This predates full-text search here, where it
  stood in for it; it is a superset, so nothing a client does breaks on it.

**`/top` answers with the parent of whatever matched.** A search that can be
satisfied by a child item — `q`, `tag`, `itemKey` or `itemType` — makes upstream
join its `itemTopLevel` table and select `COALESCE(ITL.topLevelItemID, I.itemID)`
distinctly, so a hit in an attachment's text or a child note's title surfaces
the item it hangs under. Without this the feature would be invisible in the
scope clients actually list items in, since an attachment is never top-level.
altero climbs the same way, through one self-join: item → attachment →
annotation is as deep as Zotero goes.

Two consequences worth stating, both upstream's:

- Every part is applied to the same row. A word in the parent's title and a word
  in the child's text do not add up to a match, even though either alone would
  have answered with that parent.
- `since` is deliberately not in that list. It is what a syncing client sends,
  and answering it with parents would report objects whose own version had not
  moved.

The matched item must be untrashed, and so must the parent it resolves to:
upstream joins `deletedItems` a second time on the top-level item for exactly
this, so a hit inside a trashed item's PDF does not resurrect it.

### Who added an item, and who last changed it

`Zotero_Item::toResponseJSON` puts two blocks in an item's `meta` for a group
library, and `Zotero_Items::search` sorts on them. Both are copied, including
the parts that look like oversights.

**Group libraries only.** `createdByUser` and `lastModifiedByUser` are emitted
for a group and never for a personal library, where there is one author and
saying so on every item is noise. Upstream keeps the columns in a `groupItems`
table that only group libraries have rows in; altero keeps them on `items` and
leaves them null outside a group, which is the same thing said differently.

**`lastModifiedByUser` is dropped when it equals `createdByUser`.** The test is
`$lastModifiedByUserID != $createdByUserID`, and it means the ordinary case —
somebody adding an item and then fixing its title — carries one name rather
than the same name twice. Upstream writes both columns on create and collapses
them on the way out; altero does the same, so the stored row can still answer
"who last touched this" for sorting while the response stays what a client
expects.

**The name is `Zotero_Users::getName`:** the real name, or the username when
there is none.

**No `alternate` link.** Upstream's `Zotero_Users::toJSON` attaches one
pointing at the person's profile on zotero.org. altero omits it for the reason
it omits every `alternate` link — see [Deliberate differences](#deliberate-differences).

**An account that has gone breaks nothing.** Upstream swallows the lookup
failure and emits no block; altero resolves a page's accounts in one query and
renders nothing for an id it cannot find, which arrives at the same place.

#### Sorting by a person

**`sort=addedBy` orders by the author's name**, not the username and not the
id, because that is what upstream's temp table is filled from.

**And it falls back to `dateAdded` where there is nothing to sort by.** The
condition is `if ($isGroup && $createdByUserIDs)`; without authorship the sort
becomes `dateAdded` rather than erroring. That covers a personal library, and
every group library that upgraded into this, whose items were all written
before anybody was recorded. altero asks the same question with an `EXISTS`.

Worth knowing, because it surprises: the *direction* still comes from the name
of the sort. Anything beginning with `date` counts down and everything else
counts up, so `sort=addedBy` ascends even while it is ordering by `dateAdded`
underneath, and a bare `sort=dateAdded` descends. Both are `getDefaultDirection`
behaving as documented; they simply do not agree.

**`sort=editedBy` is altero's, not upstream's.** `dataserver#153` has asked for
it since 2023 and it has not been built. The column is recorded anyway for
`meta.lastModifiedByUser`, so the sort costs nothing beyond accepting the name.
A client that sends it here and to api.zotero.org will get an answer here and
`Invalid 'sort' value` there; nothing altero can do about that, and no client
sends it today because upstream never offered it.

### Pagination of the sync formats

`Zotero_API::getLimitMax` returns `0` for `format=keys` and `format=versions`,
and their default limit is `0` as well. Zero means *no limit*: both formats
return the entire result set in one response and carry no `Link` header.

This matters more than it looks. The desktop application reads the whole of
`format=versions` to decide what to sync; truncating it to the usual 25 would
not produce an error, it would silently make the client believe the library
contains 25 objects. An explicit `limit` is still honoured for these formats,
and is not capped at 100.

For every other format the maximum stays 100 and the default 25.

### Naming objects by key

`itemKey`, `collectionKey` and `searchKey` are one case in
`Zotero_API::parseQueryParams`, and it does three things worth copying exactly.

**It does not count the keys.** Leading and trailing commas are trimmed, each
key is checked, and a malformed one is *dropped with a log line* rather than
failing the request — it could not have matched an object anyway. However many
are left, the response is paged like any other.

**It forces the page size**, to `MAX_OBJECT_KEYS`, which is **100**:
`$finalParams['limit'] = self::MAX_OBJECT_KEYS` is assigned inside that case,
so it overrides whatever `limit` the client sent. altero applies it the same
way, and leaves `keys` and `versions` alone — those answer with everything, and
holding them to a hundred would turn a complete answer into a truncated one.

**Each object type filters on its own parameter.** `Zotero_Collections::search`
and `Zotero_Searches::search` both add `AND key IN (...)`, as
`Zotero_Items::search` does for `itemKey`.

All three matter because this is the sync's *download* step. Having asked what
changed, the client fetches the objects themselves by key, in batches of
`Zotero.Sync.APIClient.MAX_OBJECTS_PER_REQUEST` — also 100. altero refused more
than 50 outright, answered a smaller batch with a 25-object page, and ignored
`collectionKey` and `searchKey` altogether. A library with fewer than 25
changed objects hides all three; one with 309 does not.

### Parameter handling

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

### Response shapes

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

**The order of `data` decides whether an attachment saves.** `Zotero.Item.fromJSON` walks the object
with `for (let field in json)` and, on reaching `filename`, sets the attachment
path — which throws "Link mode must be set before setting attachment path"
unless `linkMode` has already gone by. An attachment served the other way round
is never saved: it lands in the client's `syncQueue` and fails there on every
later sync. Field values are rows with no order of their own, so their stored
order is whatever the database returns — insertion order under SQLite, nothing
in particular under PostgreSQL — and altero puts them back into the schema's
order before emitting them, which for an attachment reads `linkMode`, `title`,
`accessDate`, `url`, `contentType`, `charset`, `filename`, `md5`, `mtime`,
`note`. That is the order zotero.org serves, read off a migrated library.

### Fields the published schema does not list

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

### Timestamps

`dateAdded` and `dateModified` come from the client and round-trip unchanged, so
uploading an existing library keeps its history instead of rewriting every item
to the moment of upload. `serverDateModified` is always the server's own, which
is what makes sorting by it trustworthy: a client cannot reorder another
client's results by backdating its own timestamps.

### Citations and bibliographies

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
`csljson`, `none` and every export format are accepted; `include=none` may not
be combined with anything; `include` outside `format=json` is a 400, as is an
unknown value. Upstream additionally accepts `html`, which needs Atom and is
asked for through `content` here.

**Every export format is written, and each is a port of Zotero's own
translator.** Upstream produces them by handing the item JSON to a translation
server running the JavaScript translators from
[zotero/translators](https://github.com/zotero/translators); altero has no such
thing, so each of the sixteen formats `Zotero_Translate::$exportFormats` names
is ported into `altero/cite/formats/`
and checked against what `api.zotero.org` answers for the same item. Six of them
— Refer/BibIX, RefWorks Tagged, Wikipedia citation templates, COinS, MODS and
TEI — reproduce it byte for byte on every item tested. CSV and EndNote XML do
too, apart from the one place each that is named below. The three RDF formats
match statement for statement, the serialiser's own whitespace aside.

`bibtex`, `biblatex` and `ris` are the exception to the porting: they are mapped
from the CSL JSON an item already renders as, with
[bibtexparser](https://github.com/sciunto-org/python-bibtexparser) and
[rispy](https://github.com/MrTango/rispy) doing the writing. Consequences worth
knowing:

- CSL is a superset of what these three formats carry, so the mapping loses
  nothing they can hold — but a type CSL renders as `document` becomes `@misc`
  or `GEN`, where a translator might have known better.
- Citation keys are generated as `surname` + `year` + first significant title
  word, disambiguated with a letter within one response. Upstream's translator
  has its own scheme; neither is stable across servers, which is why a
  `citationKey` field in the item wins over both.
- Tags become `keywords`. They are not part of CSL, so they are carried
  alongside it rather than through it.

What a translator is handed matters, and altero reproduces that too: Zotero adds
its compatibility mappings — base fields under their own names, `versionNumber`
called `version`, an access date written with a space rather than a `T` — only
for translators declaring a `minVersion` below 4.0.27. TEI is the one export
translator on the far side of that line, so it alone sees the item as the API
serves it: it reads `versionNumber`, writes no publisher for a report (whose
field is `institution`), and dates its access with a `T`.

Eight deliberate differences. The first names the application that wrote the
file; the rest are places where copying upstream would mean copying something
broken:

- **A file says altero wrote it.** EndNote XML's `source-app` and Evernote's
  `en-export application` name this server and its version, where upstream's
  name Zotero and the client version its translation server happens to run.

- **The XML and RDF formats match in content, not in whitespace.** Zotero's RDF
  serialiser indents a resource with one child differently from one with two and
  writes a line of three spaces into an empty document; the namespaces are all
  declared on the root here, because a file is written in batches and the root
  goes out before the first item. No RDF or XML parser can tell the difference.
- **CSV's `Date Added` column is the date the item was added.** Upstream writes
  `dateModified` into it, which loses the one thing the column is for.
- **Bookmarks are escaped.** The translator writes the title and the URL
  straight into the markup, so an ampersand in a title produces a file no HTML
  parser reads back the way it went in — and this server will answer
  `format=bookmarks` to a browser with an API key in the query string.
- **Evernote's ampersands are escaped once.** Upstream escapes `<` and then
  escapes every `&` over the whole document again, including the ones inside a
  CDATA section that needs none, so a title with an angle bracket arrives
  reading `&lt;` in full.
- **An Evernote `<updated>` ends in one `Z`, and an item with no URL has an
  empty `<source-url>`.** Upstream appends a `Z` to a timestamp that has one,
  and writes the string `undefined` for the URL.
- **An ISBN of two numbers separated by two spaces produces two Bibliontology
  statements, not three.** The third is empty upstream — what splitting on a
  single space does to a double one.
- **An entry's TEI `xml:id` keeps its plain form and the *second* one gains a
  letter.** Upstream renames the earlier entry and numbers from `b`; a file
  written in batches cannot go back and rename an entry already sent.

Two things a translator can be *asked* have no answer here, because an export
over the API has neither to offer: the attached files, and child notes. Upstream
sends each item on its own, so its `item.notes` and `item.attachments` are empty
as well — a note is exported as an item of its own, in the formats that write
one, or not at all.

Where a format writes something for a note, an attachment or an annotation is
the translator's own decision and is kept: CSV, Refer, BibTeX and most of the
rest skip them by name; COinS writes a span for anything; Evernote makes a note
of everything; Zotero RDF describes them, being the format a library export is
written in.

Three places where the rendered output is not upstream's:

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

One limitation is worth knowing about, and it is upstream's. citeproc-py's
`cs:label` renders its term whether or not the variable it labels has a value,
where CSL 1.0.2 says "the term is only rendered if the selected variable is
non-empty". Any style that labels a variable an item happens not to have gains a
stray word; the visible case here is the in-text citation of
`chicago-shortened-notes-bibliography` — what the API's default style name now
resolves to — which reads `Doe, “A Study of Things”, edition.` for an item with
no edition. Bibliographies in that style are unaffected, as are the citations of
every other style tried (APA, MLA, IEEE, Nature, AMA, the other Chicago
variants), and the bibliography is the path both the API and the interface lead
with. Reported upstream, with a patch.

Nothing here corrects citeproc-py's own output. `pyproject.toml` floors it at
0.11.0: altero's rendered bibliographies depend on it counting
`citation-number` as a variable call in a `cs:group` (without which a numeric
style like IEEE, whose citation groups the number with an empty locator macro,
renders nothing at all), defaulting the delimiters around a style's `and`
(without which APA reads `Doe, J.& Roe, R.` and MLA `Doe, J.and R. Roe.`), and
normalizing punctuation at a concatenation seam (without which an initialled
name reads `Doe, J..`).

### Item type schema

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

## Files and synchronization

### The file protocol

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

#### Downloading is a redirect, and has to be

`GET <prefix>/items/<key>/file` answers **302**, carrying three headers:

| Header | What it says |
| --- | --- |
| `Zotero-File-Modification-Time` | the `mtime` the uploading client declared |
| `Zotero-File-MD5` | the digest the item claims, not the digest of the bytes |
| `Zotero-File-Compressed` | `Yes` when the bytes are an archive around that file |

Upstream sends these on the redirect to S3, and the client reads them there and
nowhere else, so a 200 carrying the bytes — however it is labelled — reaches
`Zotero.Sync.Storage.Local.processDownload` with nothing set and throws
`'data.mtime' not set`. altero answered 200 and every attachment in the library
failed to download, on every sync, with "A file sync error occurred".

The client needs the redirect for a second reason. It compares
`Zotero-File-Modification-Time` with the local file and, when they match, never
asks for the bytes at all. Metadata hung on the response that carries the file
would arrive too late to save the transfer.

##### The location has to be a credential

The client does not follow the redirect. `zfs.js` asks for the file with
`followRedirects: false`, reads the three headers off the 302, and then makes a
*second, fresh* request for the location — `Zotero.HTTP.download(fileURL, …)`,
which is passed no `headers` at all. Upstream can do that because its location
is a presigned S3 URL, which is a credential in itself.

So altero's has to be one too. `GET <prefix>/items/<key>/file` grants a
short-lived permission for that one file and points at
`/storage/download/<key>`, the mirror image of `/storage/upload/<key>`: the key
in the path is the whole credential, no API key is taken there and none is
accepted. It expires after five minutes, it is checked against the digest the
302 promised so it cannot be spent on whatever the attachment holds later, and
the redirect carries `Cache-Control: no-store` so no shared cache keeps it. It
is deliberately *not* one-shot — `Zotero.HTTP.download` retries the same URL
after a 5xx or a dropped connection.

The obvious alternative, appending the caller's API key to the location as
`?key=…`, works and was rejected. An API key grants the whole account and never
expires, and a reverse proxy writes every request line to its access log; altero
ships configurations for three of them.

> [!NOTE]
> Before Zotero's April 2026 rewrite of `HTTP.download()` the client followed
> this redirect inside one channel, which carried its headers along, and the
> location could be an ordinary API route behind the same key. That route,
> `<prefix>/items/<key>/file/content`, is still served for callers that have a
> key and would rather ask for the bytes directly.

#### Telling an archive from a file

The client zips a snapshot before uploading it, and sends `zipMD5` for the
archive while `md5` keeps describing the file inside. A snapshot migrated out of
zotero.org arrives the same way. Told `Zotero-File-Compressed: No`, the
client writes the archive itself to disk under the attachment's name, which
loses the snapshot quietly.

altero records no flag for this and does not need one. The store is addressed by
the digest the item claims, so an archive is exactly a stored file whose own
digest is not the name it is stored under. The ZIP magic number is checked
first, so only archives are ever hashed, and the digest then separates a wrapper
from an attachment that is itself a ZIP — a .docx or .epub hashes to what its
item claims. Digests are cached per file identity, so a library syncing
repeatedly hashes each archive once.

## Authentication and client login

### Obtaining a key

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

### What the desktop client actually sends

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

**And it is served as a number.** Every other field value is text, and altero
stores them all as text, but upstream keeps this one in a column of its own and
emits `"mtime": 1299848186000` where `md5` beside it is quoted — read off an
attachment in public group 91 on api.zotero.org. `Item.fromJSON` ignores both
fields, so an ordinary sync never notices the difference; the one place it shows
is `Zotero.Sync.Storage.Local.resolveConflicts`, which assigns
`conflict.right.mtime` from the cached remote JSON when a file conflict is
settled in favour of the local copy, into a setter that throws
`attachmentSyncedModificationTime must be a number`. A file conflict is what two
clients editing one attachment produce, so `serializers.item` casts it back on
the way out. Found while checking the tool that
[testing-two-clients.md](testing-two-clients.md) uses to compare two clients
against the server.

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

The streaming API **is** served, at `/stream`, built from the published
protocol rather than from a reference implementation — see below.

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

`extensions.zotero.streaming.enabled = false` stops it. Because `streaming.url`
exists, the better answer is to point it at altero's own socket, which is what
`clients.md` now says: the credential stays put *and* the client stops waiting
for its next poll to hear about a change.

[streaming]: https://www.zotero.org/support/dev/web_api/v3/streaming_api

### The streaming API

Served at `/stream`. Upstream's is the root of a host of its own; altero is one
application, so it gets a path under it, and the client is pointed at it with
`extensions.zotero.streaming.url`.

What is on the wire is the [published protocol][streaming] and nothing beyond
it. Both modes work: a key in the handshake, which subscribes the connection to
everything that key can reach and lists it on the `connected` event; and
`createSubscriptions`, which is what the Zotero client sends — one subscription
naming its key and **no** topics, meaning "everything, and keep it current".

**Three topics that are not libraries.** The client names all three on
connections it opens as a matter of course, and every one of them was refused
until two clients were watched doing it:

- **`styles` and `translators`** are subscribed to whenever the client updates
  those automatically. altero publishes to neither — the client's own
  repository timer is what fetches them — so the subscription is accepted and
  never fires. Refusing it changed nothing except to put two errors in the
  log on every connection.
- **`login-session:<token>`** is how the client is told the moment a login is
  approved, instead of waiting for its next three-second poll. Subscribing
  needs the token, which is also what `GET /keys/sessions/<token>` is
  authenticated by; a token naming no session is refused rather than accepted
  and silent. On approval the topic carries `loginComplete` with the same body
  the poll endpoint returns — the client hands it straight to `checkUser` —
  and `loginCancelled` when the session is abandoned. Neither is a
  `topicUpdated`: the client registers a listener for those two events by name.
  An approval from `altero login approve` announces to nobody, because that is
  a process of its own and the broker is in memory; the client's poll finishes
  the login as it did before.

**Deleting a subscription that is not held is ignored**, and 4409 is never
sent. The client's login flow produces exactly that case: it asks to watch a
login session and unsubscribes when the login is over, whether the
subscription was granted or not. A close code it did not expect reads to it as
its own bug — "Not reconnecting to WebSocket due to client error" — and it
stops trying, so a documented code cost the connection.

**`subscriptionsDeleted` names what went.** `streamer.js` walks
`data.subscriptions` to take them out of its own set and throws on an event
without them.

**What is inferred rather than copied.** There is no dataserver source for any
of this, so these are altero's:

- **Close code 4400** for a message that is not JSON or names an action this
  server has not got. The documentation gives 4403, 4409 and 4413 and stops
  there; 4400 continues the series.
- **A per-connection subscription limit of 50.** The documented 4413 says a
  limit exists but not what it is. The Zotero client holds one subscription.
- **`topicAdded` and `topicRemoved`** are sent only to a subscription that
  named no topics. A client that listed its own chose them, and adding one it
  did not ask for would be this server deciding what it watches.

**One version per event, as one version per request.** The announcement is made
from the same place the version counter moves, and on commit rather than at the
point of change: a write that rolls back announces nothing, because a client
told about a version that was never issued would ask for it and be told the
library is older — indistinguishable, from the client's side, from a server
that had gone backwards.

**One process.** The broker is in memory. A deployment running several workers
delivers an event only to the clients attached to the worker that served the
write; the others hear nothing and fall back on polling, which is what they did
before. Streaming across workers needs a shared bus, which this is not.

### Atom

`format=atom` is served by the item, collection, saved search and tag
endpoints, for listings and for single objects, with `content` choosing the
body — `html` by default, and `json`, `bib`, `citation`, `csljson`, the three
export formats, `none`, or several at once as `zapi:subcontent` elements. The
shapes were read off `api.zotero.org`; the prose describes Atom only in
outline.

Five differences, four of them consequences of decisions recorded elsewhere in
this file:

- **No `rel="alternate"`, anywhere.** Upstream's names a page on zotero.org.
  See "Deliberate differences" below.
- **`<id>` is built on the address the request arrived on.** Upstream writes
  `http://zotero.org/users/<id>/items/<key>`, which is an identifier rather
  than a link but still names somebody else's service. An Atom id is meant to
  be stable, and altero has no fixed host to make one from, so the request's
  own is used.
- **The feed title reads `altero / <library> / <what>`** where upstream writes
  `Zotero`. The rest of the title — "Top-Level Items", "Items in Collection
  ‘x’" — is upstream's wording.
- **No `rel="first"` on the first page.** altero builds the feed's paging links
  and the `Link` header from one place, so the two cannot disagree about what
  pages exist; upstream emits `first` in the feed pointing at the page being
  read.
- **The XHTML table's rows are in the item's own field order.** Upstream orders
  them by an internal field identifier the published schema does not carry —
  the same limitation recorded under "Item type schema" for fields that share a
  localized name. The labels for fields outside the schema (`linkMode`,
  `contentType`, `charset`) are upstream's; the rest are altero's, there being
  nothing to copy.

Two smaller choices. A `<content>` carries **both** `zapi:type` and a media
`type`: upstream writes `type="application/json"` for a collection and
`zapi:type="json"` for an item, with neither carrying the other's attribute, so
emitting both means a consumer reading either finds it. And a bibliography or
citation is embedded with the XHTML namespace declared on it — citeproc
produces plain HTML, and `type="xhtml"` without the declaration would be a
claim the document does not keep. A fragment that will not parse as XML is
escaped and labelled `type="html"` instead, so one bad entry cannot make the
whole feed unreadable.

`content` is refused outside `format=atom`, and a citation form is refused on a
collection, saved search or tag, for the reason `include` is refused outside
`format=json`: a caller that asked for a citation and got an empty body has no
way to tell that from an object that has none.

### API versions

Only version 3 is served. A request naming another version through the
`Zotero-API-Version` header or the `v` parameter is refused with `400` rather
than answered. Atom is implemented now, but a v1 or v2 client expects more than
a format: different envelopes, different parameter names and different
pagination, none of which altero serves. Returning v3 bodies under a v2 label
would be worse than saying so. A header and a parameter that disagree are also
refused, as upstream does.

### The `relations` map

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

### Backoff and Retry-After

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

## Libraries, groups and altero extensions

### My Publications

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

#### Who may read My Publications

Upstream: anybody. The list is served without a key, and there is no setting.

altero keeps that as the default and lets the account narrow it, because a
personal server is not a service — see
[web/sharing.md](web/sharing.md#who-can-see-it). The setting is one column
on the account, `public` for every account that existed before it did, and it is
enforced on the v3 endpoints as well as on the profile page:

| Setting | Keyless | Any key this server issued | A key that may read the library |
| --- | --- | --- | --- |
| `public` (default) | 200 | 200 | 200 |
| `users` | 403 | 200 | 200 |
| `private` | 403 | 403 | 200 |

The last column is why the owner's desktop client is unaffected: it syncs My
Publications with a key that can read the library it belongs to, so closing the
page never breaks the sync that filled it. Every publications endpoint asks —
`items`, `items/top`, one item, and the `settings` and `deleted` polls — because
a closed list that still reported its version to anyone would be describing a
library it had refused to show.

An instance that never touches the setting behaves exactly as the dataserver
does, which is what upstream's own test file expects when it reads every case
with `API::useAPIKey("")`.

#### Profile pages

Upstream's profile page is `zotero.org/<slug>`, built by
`Zotero_URI::getUserURI` from the username put through
`Zotero_Utilities::slugify` — lower case, everything outside `[a-z0-9 ._-]`
dropped, spaces to underscores. altero serves the same page from its own
interface at `/app/u/<username>`, under a prefix, because a bare path would
collide with the interface's own route names: an account called `settings` would
otherwise have no page, and every route added later would silently claim a
username. Both the username and upstream's slug of it resolve, and neither is
matched case-sensitively.

`Zotero_Users::getName` falls back from the profile's real name to the username,
and so does the heading here. There is no `alternate` link to zotero.org for the
same reason the item envelopes carry none: altero will not point a reader at
somebody else's copy of the data.

#### Publishing from the browser

Setting `inPublications` is all the v3 API knows about publishing, and it is
not all publishing *is*. The desktop client asks four things before it sets the
flag, in `publicationsDialog.js`, and acts on them in
`Zotero.Items.addToPublications`: whether the item's files go along, whether
its notes go along, whether an existing `Rights` value stands, and under what
licence the files are published. altero's browser interface asks the same four
and sends them to endpoints of its own, `PUT` and `DELETE` on
`/web/libraries/<id>/publications/items/<key>`, which are cookie-authenticated
like everything under `/web` and never reachable with an API key. The rules
they enforce are the client's:

| Rule | Where it comes from |
| --- | --- |
| Child notes go only with `includeNotes` | `options.childNotes` |
| Stored attachments go only with `includeFiles` | `options.childFileAttachments` |
| Link attachments always go | the client's own drop passes `childLinks: true` |
| Linked files never go | `LINK_MODE_LINKED_FILE` is skipped in the loop |
| Annotations never go | the drop passes `annotations: false` |
| The licence is written into `rights` unless `keepRights` and the field already says something | `if (!options.keepRights \|\| !item.getField('rights'))` |
| Removing takes the item's notes and attachments out with it, trashed ones included | `getNotes(true).concat(getAttachments(true))` |
| Removing something that is not published is an error | `throw new Error(...is not in My Publications)` |

Two deliberate differences:

**The licence name is English, whatever language the account reads in.** The
client writes the name its own window was showing, so the same licence reaches
the field as `Creative Commons Namensnennung 4.0 Internationale Lizenz` from a
German client and in English from a Japanese one, whose catalogue leaves the
strings untranslated. `rights` is data — exported, cited, read by every other
client — rather than a label this server draws, and altero has no message
catalogue on the server side to draw it with. The table of licences lives in
`services/publications.py`; the interface holds the same table in
`web/src/publications/licenses.ts` and shows the name the item will carry
rather than a translation of it, and `tests/test_web_publications.py` fails if
the two disagree.

**The licence can be changed afterwards; the wizard cannot be re-run.** The
client's drop skips an item that is already published — `if (item.inPublications)
{ ... continue; }` in `collectionTree.jsx` — so the wizard sets a licence once,
and a desktop user who wants a different one edits the item's **Rights** field
in the Info pane, where it is an ordinary field. altero's browser has no field
editor, so it grew the same escape hatch in the narrowest form that works: the
item `PATCH` under `/web` takes a `fields` object limited to an allowlist that
holds `rights` and nothing else (`EDITABLE_FIELDS` in
`api/routes/webitems.py`). Unlike the other writes that door makes, it carries
the version it replaces and is refused if the item has moved on, because text
is not an errand the server can reconstruct from what is stored.

**The client's generic `cc` licence is not offered.** It is what its wizard
reports while a Creative Commons licence is still being chosen, and it reaches
`rights` only on the one path where `keepRights` means nothing is written
anyway. Choosing Creative Commons here always leads to the two questions that
narrow it to one of the six.

### Trashing a collection or a saved search

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

### `inPublications`

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

**A partial write that does not mention it leaves it alone**, and so does one
that does not mention `deleted`:

```php
if (isset($json->deleted) || !$partialUpdate) { $item->deleted = ...; }
if (isset($json->inPublications) || !$partialUpdate) { $item->inPublications = ...; }
```

Both lines are `Zotero_Items::updateFromJSON`, and altero followed neither for
items — it applied both flags on every write, so a `PATCH` of a title took the
item out of the trash and out of My Publications. Collections and searches had
the rule from the start (see *Trashing a collection or a saved search*); items
now do too. A `PUT` still clears what it omits, and the client writes
`deleted: false` explicitly when the flag goes away rather than dropping the
key.

The public listing of published items is served — see *My Publications* above.
Putting an item into that list from the browser, with the options the desktop
client's wizard offers, is *Publishing from the browser* below.

### A POSTed batch is a batch of patches

`Zotero_DataObjects::updateMultipleFromJSON` passes `$partialUpdate = true` for
every object in the batch, and each type's validator is then called with
`$partialUpdate && $exists`. So in a `POST` to `/items`, `/collections` or
`/searches`:

- an object naming one that **exists** may leave out anything it is not
  changing, and what it leaves out is left alone;
- an object that is **new** must still carry what a new object needs — a
  collection its name, a search its conditions, an item its type.

`PUT` is the replacing write and stays one: what it omits, it clears.

This is not a corner of the protocol, it is the normal upload. The client keeps
the last synced copy of each object in its `syncCache` and passes it to
`Zotero.DataObjectUtilities.patch` as a base, so what goes up is the
difference. Two shapes matter:

| The user did | What the client uploads |
| --- | --- |
| Sent a collection to the trash | `{key, version, deleted: true}` |
| Changed an item's type | `{key, version, itemType}` |

altero read both as replacements. The first was refused with `400 'name'
property not provided`, and since the client stops on a rejection —
"Made no progress during upload" — one trashed collection wedged the whole
library's sync, in both directions. The second was worse: it succeeded, and
emptied the item of every field, creator, tag and collection the patch did not
mention.

**A property that is absent means "as before"; clearing one is done by
sending it empty.** The client already does exactly that — `patch()` writes
`deleted: false` rather than dropping the key, and sends `relations: {}` rather
than omitting the map — so nothing depends on omission meaning erasure.

That distinction has to hold for the four properties holding a *list* —
`creators`, `tags`, `collections` and `relations` — and not only for the two
flags. `updateFromJSON` walks the properties the object carries,
`foreach ($json as $key=>$val)`, and hands each straight to its setter, so
`collections: []` reaches `setCollections([])` and files the item nowhere;
only an absent property is skipped. Reading empty and absent as one thing
leaves no way to say "none", and the desktop client asks for exactly that on
an ordinary path: save through the connector into a collection, then move the
save target to the library root, and it uploads
`{key, version, collections: [], dateModified}`. Ignored, that write appears
to succeed while the item stays filed, the client re-files it locally from the
answer, and every following sync uploads the same patch again — a library that
takes a new version each time and an item that can never leave its collection.

An item with no creators carries no `creators` property at all
(`if (!$arr['creators'] && !$includeEmpty) unset($arr['creators'])`), while
`tags`, `collections` and `relations` are emitted even when empty. That
asymmetry is upstream's and is mirrored.

### Objects that were sent again without changing

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

### Groups

Upstream serves `POST /groups`, `PUT /groups/<id>`, `DELETE /groups/<id>` and
`POST /groups/<id>/users`, and none of them is part of the API a client uses:
all require `$this->permissions->isSuper()`, which `ApiController` grants only
to an operator authenticating out of band rather than with an API key, and all
take an **XML** body parsed with `new SimpleXMLElement($this->body)`. Asking
`GET /groups/<id>/users` with an ordinary key answers `403 Forbidden`. It is
zotero.org's own administrative back door, and the Zotero client never calls
it.

altero serves the same paths with the credential and the body format the rest
of the v3 API uses: an **API key**, and **JSON** in the shape
`GET /groups/<id>` already returns, so what was read can be sent straight back
— the `data` envelope is accepted as well as a bare object. Inventing a
superuser credential was the alternative, and it would have meant a second
class of credential on a server whose whole permission model is per library.

`PUT` replaces and `PATCH` updates in place, as they do for items: a `PUT`
without a `type` resets the group to `Private`, which is the safe direction for
the one property that decides who may read it. `POST /groups/<id>/users` names
somebody by `userID` or by `username`. `GET /groups/<id>/users` answers a shape
of altero's own, since upstream answers 403 to anything an API key can present.

Who may do what:

| | Requires |
| --- | --- |
| Create a group | a key that may write to its owner's own library |
| Read one | membership, or a public group |
| Write items to one | membership, plus `libraryEditing` |
| Upload files to one | membership, plus `fileEditing` |
| Change the metadata, add or remove members | administrator of the group |
| Leave | nobody's permission but your own |
| Hand it on, delete it | the owner |

Two of those are new rules rather than copied ones. A key must be **allowed to
write** to a group *and* its owner must **administer** it, because putting
items in a library and deciding who else may are separate things; and only the
owner can transfer or delete, because both end the group as its members know
it.

**Membership is a ceiling, and it did not used to be.** `access_for` read a
key's "all groups" grant as *every group on the server* rather than every group
its owner belongs to, so anybody holding such a key could read — and write —
every private group library on the instance. This surfaced the first time the
new endpoints were driven with curl: a second account read a private group it
had never been added to. It is fixed here, with `access_for` taking the
caller's membership and the group's own policy alongside the key's grants.

The version counter moves for a metadata write and for a membership change
alike. Upstream keeps a group version apart from the library's; altero reports
the library's as both, so a role change costs connected clients one sync poll
that finds nothing new. That is the cheaper mistake: a client that has not
noticed it was demoted is one that still believes it may write.

### Finer roles for one member

A Zotero group decides who may edit as a property of the group — `members` or
`admins`, the same answer for everybody in it. A read-only member, one who may
add but not delete, and one who may edit only their own items have been asked
for on the forums since 2010
([discussion 14053](https://forums.zotero.org/discussion/14053/)), answered
with "more fine-grained permissions have long been on the agenda", and none of
them has shipped. altero has all three, as a **per-member permission** stored
on the membership beside the role.

The two answer different questions. A role says whether somebody helps run the
group; a permission says how far they may go in what is in it. So an
administrator can be an ordinary contributor, and a member can be held to
reading without anybody's role changing.

| Permission | Creates | Changes | Removes | Collections and searches |
| --- | --- | --- | --- | --- |
| `inherit` | ✓ | ✓ | ✓ | ✓ |
| `read` | | | | |
| `add` | ✓ | anything | | make and change, never remove |
| `own` | ✓ | its own | its own | read-only |

Four things decide how it behaves, and each is a decision rather than a
derivation:

**It is a ceiling, never a grant.** It joins the key's permissions, the
membership and the group's own policy, and it is applied last: a member marked
`add` in a group that reserves editing for its administrators has already lost
write access before their permission is looked at. `access_for` in
`services/auth.py` is where all four meet.

**Trashing counts as removing.** Setting `deleted` is how the desktop client's
Delete does its work, so a member who may not delete but may trash could still
empty a library in one gesture — which is what the forum thread was posted
after. Restoring something from the trash is not a removal and stays allowed.

**The shared structure belongs to nobody.** Nothing records who made a
collection, a saved search or a library setting, so `own` cannot tell one
member's from another's and treats all of it as somebody else's. Filing an item
into a collection is a write to the *item* and stays allowed, which is what
makes `own` usable: a contributor puts their own work wherever the group's
structure says it goes and cannot restructure it.

**An administrator cannot be restricted.** They can edit any membership,
including their own, so a restriction on one would be a thing the interface
displayed and nothing enforced. Setting one is refused, and promoting somebody
to administrator clears theirs.

#### One library version, two representations

Only `read` can be said in a vocabulary a sync client already understands, and
this is how it is said: `libraryEditing` renders as `admins` in **that
member's** view of the group, and as whatever is stored to everybody else. The
client then draws the library read-only with no idea that anything new exists,
which is exactly what it does for every ordinary member of a group whose
editing is reserved.

That gives one library version two representations, which was the question this
feature turned on. It is settled by what the group resource already was: `GET
/groups/<id>` answers **404** to a stranger and **200** to a member, and `GET
/users/<id>/groups` is by definition the caller's own list. The group has never
had a single representation for a per-member one to break. What a client
compares versions against is its own view, and that view changes only when the
library version moves — which setting a permission does, like every other
membership change.

`services/groups.editing_for` is the whole of it, and it is the only place the
rendered value can come from.

#### `add` and `own` surface as sync errors

Neither has any client vocabulary, and altero does not invent one: they are
enforcement and nothing else. A desktop client belonging to a restricted member
draws the library as writable, because as far as `libraryEditing` is concerned
it is, and a write the permission forbids comes back **403** with a sentence
saying why:

- `You can add to this group library but not remove from it`
- `You can only change what you added to this group library`
- `You can only remove what you added to this group library`

The client shows that as a sync error. It is said in words rather than as a
bare `Forbidden` because it is the only explanation the person holding the
restriction is going to get. Anybody setting `add` or `own` on a member should
know that is what it will look like from the other side; the browser interface
knows about both and does not offer the controls, which is the only place the
restriction can be shown before it is hit.

#### Where a permission is set

`PUT /groups/<id>/users/<userID>` takes `permission` alongside `role`, and
either alone. Both in one request applies the role first, so a demotion
followed by a restriction ends on the restriction rather than on the `inherit`
the promotion rule would otherwise have left. `GET /groups/<id>/users` reports
it. The browser sets it on the group's member list, an invitation can carry one
so that "come and read this" and "come and help with this" are different
invitations, and `altero group permission <group> <username> <permission>` does
it from a shell.

### Renaming a tag

`PATCH <prefix>/tags/<name>`, taking `{"tag": "<new name>"}` and answering
`204` with the new `Last-Modified-Version`. Nothing upstream serves this.
`TagsController::tags` allows `HEAD`, `GET` and `DELETE`, and a named tag only
`GET`, so a rename has to be done by the client, item by item —
[zotero/dataserver#108](https://github.com/zotero/dataserver/issues/108) has
asked for it since 2016 and is still open, with no discussion of a shape to
copy. The endpoint is therefore altero's own, and the behaviour behind it is
copied from the one implementation that does exist: `Zotero.Tags.rename` in
the desktop client.

That is what settles the questions the operation raises:

- **A name may be two tags**, one added by hand and one by a translator, since
  the type belongs to the tag rather than to its attachment to an item. Both
  are renamed, as `DELETE <prefix>/tags?tag=` removes both.
- **What is left is exactly one tag under the new name**, carrying every item
  that was under either name. That includes absorbing an *automatic* tag
  already called that: skipping it would leave the library with two tags of
  one name, and `/tags` would list the name twice. The client cannot produce
  that — its `tags` table is unique on the name alone, with the type on the
  item's link — so neither may this.
- **What survives is manual.** The client's rename sets `type=0` on every link
  it moves (`UPDATE OR REPLACE itemTags SET tagID=?, type=0`), and
  `Zotero.Item.replaceTag` does the same for one item. Renaming is how an
  automatic tag stops being one.
- **An item that was already under the new name is left alone**, since nothing
  about it is different afterwards. A tag is attached to an item at most once,
  so an item that carried both ends up carrying it once.
- **Every item under a tag that went gets the new library version** and a new
  `serverDateModified` — it gains the new name, loses a duplicate of it, or
  stops being automatic. This is the part that matters for syncing: a tag's own
  `since` listing tells a client only about tags, while the item JSON is where
  the name actually lives. The client's rename marks the same items unsynced.
  Their `dateModified` is left alone — the client did not do this, and client
  timestamps round-trip.
- **The old name goes into the delete log**, exactly as deleting it would put
  it there, and any entry for the *new* name is cleared. Upstream clears the
  same row whenever a tag is saved under a name that had been deleted
  (`Zotero_Tag::save`); without it one sync can tell a client both "remove this
  tag" and "here are items carrying it", and which it applied last would decide
  whether the tag survived.

`If-Unmodified-Since-Version` is required, as it is for `DELETE
<prefix>/tags`. Renaming to the name the tag already has changes nothing and
does not move the library version; an unknown tag is a `404`; a name that is
empty after trimming, or longer than the 255 characters the column holds, is a
`400`.

The browser reaches the same service through `PATCH
/web/libraries/<id>/tags/<name>`, which takes a cookie and a CSRF token instead
of a key and no version header. See
[web-interface.md](web-interface.md#tags).

### The desktop client's three extra views

The client's sidebar holds three rows that are not collections and not scopes
the v3 API has: **Recently Read**, **Duplicate Items** and **Unfiled Items**.
The client answers all three from the copy of the library it keeps locally, and
the dataserver has no endpoint for any of them — grepping `controllers/` and
`model/` for either name finds nothing. There is nothing to copy, so what
altero serves at `scope=recentlyread`, `scope=duplicates` and `scope=unfiled`
under `/web/libraries/{id}/items` is its own, and is only offered to the
browser: the v3 API is unchanged, because a syncing client works these out for
itself and would not thank a server for a second opinion.

**Unfiled Items** is the one that needs no guessing: a top-level item in no
collection, not in the trash. That is what the name says and what the client
shows.

**Duplicate Items** is a judgement, and `services/duplicates.py` states which
one. Two items are the same work if they share a DOI or an ISBN — compared with
the punctuation, casing and any `https://doi.org/` prefix taken off — or if
they share a title, compared with punctuation and casing removed, *and* have a
creator surname in common or the same year. A shared title alone is not enough,
because "Introduction" and "Annual Report" are titles many works have; where
neither item states a creator or a year, the title stands alone. Item types are
deliberately not compared, so a book and a book section of one work are shown
as the pair somebody is looking for. Notes, attachments and annotations are
never compared at all.

**Recently Read** is the guess. Zotero 7 writes `lastRead` onto an attachment
when its reader closes, and syncs the field like any other, so the data is
here — but which items the client's own row lists, and over what window, is not
documented anywhere altero can read. It lists the item whose attachment was
read in the last 90 days, most recently read first where the sort allows it,
and the attachment itself where it has no parent. **The 90 days is a guess**:
without it the row would grow into "everything ever opened", which is not what
a row called Recently Read is for.

### Reading a library out of zotero.org

Everywhere else in this document altero is answering requests. This is the one
place it makes them: `services/zoteroapi.py` reads a personal library from
api.zotero.org so it can be copied here, and `services/zoteroimport.py` turns
what comes back into the archive `altero library export` writes. The restore is
then the existing one, so nothing about writing a library is implemented twice.

**Only an API key will do.** api.zotero.org documents exactly three ways to
authenticate — a `Zotero-API-Key` header, `Authorization: Bearer`, and a `key`
query parameter — and tells third-party software to use OAuth 1.0a. There is no
password sign-in to drive, and OAuth would need every altero instance to
register a client with Zotero. So the key is pasted in, used, and dropped.

**Three things the API does not serve**, and what altero puts in their place:

| Missing | Instead |
| --- | --- |
| `serverDateModified` | The client's own `dateModified`, which is the same instant for anything the client last wrote |
| Timestamps for collections, searches and tags | The moment of the migration. Neither server exposes them over the API |
| Versions in `/deleted` | The library's current version, so a client asking what went since any earlier point is told about all of it |

**Object URIs are rewritten by user id, and only by user id.** Relations —
`dc:relation` between related items, `owl:sameAs`, the merge tracker's
`dc:replaces` — are identifiers of the form
`http://zotero.org/users/<id>/items/<key>`. The `<id>` is the source account's
and becomes the target account's, or every related-items link would name a user
this server has never heard of. The **host is left alone**, because it is a
namespace rather than an address: `Zotero.URI.defaultPrefix` in the client is a
hard-coded `http://zotero.org/` and its parser is anchored to that literal, so
a URI naming this server instead would simply stop matching and take related
items, merged-item tracking and `owl:sameAs` with it. A relation pointing into
a *group* is left as it is: groups are not migrated, so aiming it at a local
group would be worse than leaving it where it came from.

**Throttling is obeyed as the client obeys altero's.** `Backoff` pauses before
the *next* request rather than after the one that carried it, so a page that
arrived is used; `429` waits out `Retry-After` and repeats the request, and
doubles its own delay from one second when the header is missing. Both headers
must be whole seconds and are ignored otherwise, which is the rule
`Zotero.Sync.APIClient._checkRetry` applies in the other direction. Requests go
one at a time, under the four Zotero asks for.

**`/tags?format=versions` answers 500 on api.zotero.org.** For any limit, for
every library tried, including Zotero's own documented example account —
while `/items`, `/collections` and `/searches` answer the same format
perfectly. altero implements the endpoint and answers it, so reading one
altero into another cannot show this up; a real migration died on it after
reading everything else.

So the migration divides what it reads in two. **Items, collections and saved
searches are the library**, and a request for one of those that will not answer
stops it: what would be left is not a copy. **The tags' versions, the settings,
the full text, the deletion log and each attachment's bytes** are read if they
can be and named in the report if they cannot. A tag whose version did not come
takes the library's, which errs in the safe direction — a client asking what
changed since any earlier point is told about it.

**Pages are walked with `start`, not the `Link` header.** The header names
api.zotero.org absolutely, so following it would send a fetch pointed anywhere
else — a test, a proxy, another altero — back to the real thing halfway
through.

## The authorization server

### A second credential for the v3 API

altero's central authentication rule is that the v3 API is authenticated by a
credential presented on the request and **never** by a browser cookie. The
authorization server widens what that credential may be — an OAuth access token
now works where an API key does — and it does not touch the rule itself.

The distinction is the whole reason this was allowed. A cookie is attached by
the browser to any request a third party can provoke, which is why letting one
reach `/users/<id>/items` would put the entire sync protocol behind a CSRF
target. A bearer token is attached by the application that holds it and by
nothing else; a page on another origin cannot cause one to be sent. So the
reason the rule exists is untouched, and
`tests/test_oauth.py::TestTheApiKeyPathIsUntouched` holds both halves: an API
key still works, and a session cookie still does not.

What did not widen: `/keys/current` and `/keys/{key}` refuse an access token.
Those endpoints are about an API key as an object — what it grants, and revoking
it — and a token has no row there, is not what a person revokes, and would leave
`DELETE /keys/current` with nothing to delete.

### Signing ID tokens while still not verifying them

These two decisions look contradictory, but they are not:

As a *client*, altero does not verify the signature on an ID token it receives —
see [below](#not-verifying-the-id-tokens-signature). As a *provider*, it signs
the ID tokens it issues, with RS256, and publishes the key at
`/oauth/jwks.json`.

The earlier decision was about verification, and every reason given for it is a
verification problem: `alg: none`, HMAC-versus-RSA confusion, a key chosen by an
attacker-supplied `kid`, a JWKS fetch that is itself a request to get right.
Each is a decision made about input somebody else controls. Signing has none of
them — the algorithm is fixed, the key is this server's own, and nothing reads a
header — so `services/jws.py` writes it directly rather than bringing in a
library, and `tests/test_jws.py` holds it against RFC 7515 Appendix A.2 and
RFC 7638 §3.1. A published test vector is what makes hand-writing one of these
defensible, which is the same bargain `services/totp.py` takes with RFC 6238 and
the reason `services/saml.py` does *not* hand-write its signatures.

### No dynamic client registration

RFC 7591 is not implemented and will not be. The set of addresses an
authorization code may be sent to is the entire security of the flow: the code
travels through the browser, and the only thing keeping it from travelling to
somebody else is that its destination was written down first. An endpoint that
adds entries to that list on request is not a list.

Registering is therefore an operator's act, from the command line — the same
place a group's policy is set, and for the same reason: it is a decision about
the instance rather than a use of it.

### PKCE is required, and `S256` is the only method

RFC 7636 allows `plain`, where the challenge *is* the verifier. Anyone who
intercepts the code has also intercepted everything needed to spend it, which is
precisely the attack PKCE exists to stop. altero neither advertises `plain` in
its discovery document nor accepts it, and requires PKCE of confidential clients
too, where the RFC only recommends it.

### Scopes are refused rather than narrowed

An unknown scope, a scope the client is not registered for, and a scope that is
useless without another are all errors. The alternative — issuing a token
without them — produces an application that half works and a person who cannot
tell which half. `library.write` without `library.read` is the useless case:
write access implies read access in `access_for`, so a token holding only the
former would be granted and then do nothing.

Note what is *not* in the list: there is no `annotations.*` scope. Annotations
are items in Zotero's model and there is no separate gate for them anywhere in
the API, so a scope claiming to grant them alone would be a label on a
permission that does not exist.

## Identity-provider security notes

### Not verifying the ID token's signature

Not a compatibility decision — nothing upstream has an opinion, since zotero.org
has no single sign-on — but the same kind of decision, and recorded here for the
same reason: it looks wrong at a glance and is deliberate.

altero does **not** verify the signature on an OpenID Connect ID token. The
token is fetched by altero directly from the token endpoint over TLS, and
OpenID Connect Core §3.1.3.7 item 6 permits exactly that case to be validated by
the connection instead: *"If the ID Token is received via direct communication
between the Client and the Token Endpoint, the TLS server validation MAY be used
to validate the issuer in place of checking the token signature."*

Taking that path is what keeps a JWS implementation out of this codebase, and
with it every way one goes wrong — `alg: none`, HMAC-versus-RSA confusion, a key
chosen by an attacker-supplied `kid`, a JWKS fetch that is itself a request to
get right. `services/oidc.read_id_token` reads the payload and never looks at
the header, so there is no `alg` for anybody to lie about.

What it rests on is two conditions, and both hold by construction:

- **The client is confidential.** A secret is configured and sent on the token
  request; the flow is authorization code with PKCE, and there is no implicit
  or hybrid path.
- **The token came from the token endpoint on that connection**, not from the
  browser. Nothing here accepts a token as a request parameter.

Every *claim* check is still made, and with the signature out of the picture
they are where the security is: `iss`, `aud`, `azp`, `nonce`, `exp`, `iat` and
`sub`, in `services/oidc.validate_claims`, with `tests/test_oidc.py` holding one
test per way a token could otherwise be somebody else's.

**If a public client is ever wanted here, this has to be revisited first.** The
exemption does not cover one, and a signature verifier would have to be written
before the flow could be offered.

### Reading a SAML assertion out of what was signed

The same kind of decision as the one above, and the reason it is written down:
the code looks like it is doing less than it should.

`signxml` verifies the XML signature; altero does not attempt to. Hand-rolling
that is not on — canonicalisation is where implementations grow
signature-wrapping holes, and the defence is structural rather than a check.
`XMLVerifier.verify` returns the **signed subtree**, and every claim
`services/saml.py` reads comes out of that return value and never out of the
document that was parsed. An attacker who wraps a forged assertion around a
genuine signed one gets a verified subtree that is still the genuine one, so
the forgery is simply not what is read.

What `signxml` does not do is here, and each of these is a way a perfectly
valid signature still means nothing:

| Check | Why the signature does not cover it |
| --- | --- |
| `Status` is `Success` | A failed sign-in is signed too |
| `Conditions` window, with skew | An assertion from last year is still signed |
| `AudienceRestriction` | The directory signed it for a *different* service |
| `Recipient` | It was minted for another address of ours |
| `InResponseTo` | It answers a sign-in nobody here started |
| Replay | Nothing in SAML stops one being presented twice |

Three deliberate limits: **SP-initiated only**, because an unsolicited assertion
has no `InResponseTo` to match and accepting one means accepting anything that
key ever signed; **no encrypted assertions**, since TLS covers the transport;
and **no Single Logout**, which is unreliable in practice and altero's session
is its own.

## Deliberate differences from zotero.org

### Deliberate differences

Six places where altero does not copy upstream:

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
- **A tag can be renamed over the API.** Upstream has no endpoint for it and
  leaves the work to the client; altero serves `PATCH <prefix>/tags/<name>`,
  described above. An addition rather than a divergence — nothing that reads
  tags behaves differently for it — but it is a route the reference server does
  not have.
- **altero makes requests of its own.** Only one: reading a library out of
  api.zotero.org when somebody moves one in, described above. The reference
  server is answered, never asked.
