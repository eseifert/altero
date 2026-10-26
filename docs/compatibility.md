# Compatibility reference

This page records how altero behaves where the published Zotero API documentation is silent, vague or wrong, and where altero deliberately does something different.

## How to use this reference

altero is built for the unmodified Zotero desktop application. One rule decides every disagreement:

> When the published documentation and what the real client needs disagree, the real client wins.

The evidence comes from three places, in this order:

- the live API at `https://api.zotero.org`, compared response by response;
- the source of the official [dataserver](https://github.com/zotero/dataserver); and
- real Zotero clients and libraries, where the first two say nothing.

Each section says what altero does and why. The later sections cover features zotero.org does not have, such as finer group roles, renaming tags and the authorization server, and record the decisions behind them.

## API queries and response behavior

### Omitted note content in partial writes

A partial write that leaves out `note` keeps the existing note text, for notes and attachments alike. Sending `note: ""` clears it. A full replacement (`PUT`) still replaces everything. This matches the dataserver, which only touches the note when the property is present.

### Racing ZIP archives of different sizes

When the client uploads a web snapshot, `md5` describes the file inside the archive and `zipMD5` the archive itself. Two clients zipping the same snapshot produce archives of different sizes with the same `md5`.

If a registration does not match the archive already stored, altero refuses it but keeps the stored archive, even when it is smaller, because another upload or attachment may already depend on it. Truncated files and ZIPs with broken checksums are still removed.

### Search syntax

The `itemType` and `tag` parameters behave differently from what the documentation suggests, in two ways that change results.

**Negation covers the whole value.** `itemType=-book || journalArticle` excludes *both* types; it does not mean "not a book, or a journal article". This was confirmed by counting against a real library of 442 items: `itemType=attachment || note` matched 134 and `itemType=-attachment || note` returned exactly 308.

**`||` only separates when there is whitespace on both sides.** `tag=a||b` is one tag literally named `a||b`, and so is `tag=a ||b`. This lets a tag containing `||` round-trip. Every documented example uses the spaced form, so clients are unaffected.

A leading hyphen is escaped as `\-`. Only the whole value is trimmed, once, so inner spacing in `tag=foo bar || bar` survives.

### Quick search and full-text search

`q` follows its own rules.

**Words are combined with AND, fields with OR.** Each word must appear somewhere in the title, a note's title, a creator's name or the year. `q=call me` needs both words, not the phrase; `q="call me"` needs the phrase. Single quotes never group words.

**`q=0` matches everything.** The dataserver drops an unquoted `0` before searching, so a query of just `0` filters nothing. `q="0"` searches for it. Copied rather than corrected.

**`qmode=everything` also searches attachments' text.** The matching item is the attachment itself, not the item it belongs to.

zotero.org answers this from Elasticsearch. altero does not run a search cluster — that is exactly the kind of dependency [Motivation](motivation.md) rules out — so it matches the stored text as a substring, using a trigram index in the database (see [Database requirements](deployment.md#database-requirements)). Three differences follow:

- **Characters, not words.** zotero.org matches whole words, with the last one as a prefix. altero matches characters, which cuts both ways: `q=equod` finds *Pequod*, which zotero.org would not, but `q="Pequod sailed"` does not find *Pequod, sailed*, which zotero.org would. Neither server stems, so `q=sailing` finds *sailed* on neither.

  **Accents are not folded, and Chinese and Japanese text matches as a phrase.** `q=cafe` does not find *café*, here or on zotero.org. Zotero 9 made the *desktop's* own search ignore accents, but that is its local copy; the API is accent-sensitive on both servers. `量子計算` needs those four characters in a row, which is the behavior the desktop had to be fixed to produce. What zotero.org's analyzer does is taken from Elasticsearch's documented defaults, not observed.

  **Case is ignored in every alphabet, on every database**: `über` finds `ÜBER`, in attachments' text and in every field.

  A search term shorter than three characters cannot use the index and reads every text, which is slower. `%` and `_` act as wildcards, in the text as in the fields: `q=col_ur` finds *colour*. zotero.org has no wildcards.
- **No 300-result cap.** zotero.org asks Elasticsearch for 300 hits and silently drops the rest. altero returns every match: the limit is an accident of how zotero.org fetches hits, not part of what the API means.
- **More fields are searched.** zotero.org searches the title, creators, year and attachment text. altero searches every field, so a match on `publisher` is found here only. This is a superset, so no client breaks on it.

**`/top` answers with the parent of whatever matched.** When a search can match a child item — through `q`, `tag`, `itemKey` or `itemType` — a hit in an attachment's text or a child note's title returns the top-level item it belongs to. Otherwise full-text hits would never appear in the top-level list clients actually show.

Two consequences, both copied from zotero.org:

- All words must match the same item. A word in the parent's title plus a word in its attachment's text is not a match.
- `since` does not climb to the parent. Syncing clients send it, and reporting a parent whose own version did not change would be wrong.

Neither the matched item nor the parent it resolves to may be in the trash, so a hit inside a trashed item's PDF does not bring it back.

**A tag search minds case.** `/tags?q=fic` does not find *Fiction*, as on zotero.org and in the desktop's own local API. `%` and `_` act as wildcards there too, and `\` escapes them: searching for `50\%` finds *50%* but not *500*.

### Who added an item, and who last changed it

In group libraries, an item's `meta` names who created it and who last changed it. Both behaviors below are copied, including the parts that look like oversights.

- **Group libraries only.** `createdByUser` and `lastModifiedByUser` never appear in a personal library, where there is only one person.
- **`lastModifiedByUser` is left out when it is the same person as `createdByUser`.** The common case — somebody adds an item and then fixes its title — shows one name, not the same name twice.
- **The name shown** is the person's real name, or their username when they have none.
- **No `alternate` link** to a profile on zotero.org — see [Deliberate differences](#deliberate-differences).
- **A deleted account breaks nothing.** The block is simply left out.

#### Sorting by a person

**`sort=addedBy` orders by the author's displayed name.** Where nobody is recorded — any personal library, and group items written before authorship was recorded — it sorts by `dateAdded` instead of failing.

The sort *direction* still follows the sort's name: anything starting with `date` defaults to descending, everything else to ascending. So `sort=addedBy` ascends even when it falls back to `dateAdded`, while `sort=dateAdded` descends. This is zotero.org's behavior.

**`sort=editedBy` is altero's own.** It has been requested from zotero.org since 2023 ([dataserver#153](https://github.com/zotero/dataserver/issues/153)) and not built. zotero.org answers `Invalid 'sort' value` to it; no client sends it today.

### Pagination of the sync formats

`format=keys` and `format=versions` have no page limit by default: they return everything in one response, with no `Link` header.

This matters. The desktop reads the whole of `format=versions` to decide what to sync. Cutting it to the usual 25 would not cause an error — the client would silently believe the library holds 25 objects. An explicit `limit` is still honored and is not capped at 100.

Every other format keeps a default of 25 and a maximum of 100.

### Naming objects by key

`itemKey`, `collectionKey` and `searchKey` behave alike:

- **Malformed keys are dropped, not refused.** They could not have matched anything anyway.
- **The page size is always 100**, whatever `limit` says. `format=keys` and `format=versions` are exempt and still answer with everything.
- **Each object type filters on its own parameter**: `collectionKey` for collections, `searchKey` for saved searches.

All three matter because this is how a sync downloads changed objects: by key, in batches of 100. A library with fewer than 25 changes would hide any mistake here; one with hundreds would not.

### Parameter handling

| Behavior                                                                                    |
|---------------------------------------------------------------------------------------------|
| `limit=0` or a negative limit falls back to the default rather than erroring                |
| A limit above the maximum is lowered to it, not refused                                     |
| `sort=asc` / `sort=desc` sets the direction and keeps the default sort                      |
| `qmode` ignores case, so `startsWith` and `startswith` both work                            |
| Sorts whose name begins with `date` default to descending; everything else to ascending     |
| `itemType` may not be repeated                                                              |
| `numItems` is a valid sort only for tags                                                    |
| `extra` and `serverDateModified` are valid item sorts                                       |

### Response shapes

These were confirmed against a live library.

- **A tag has no version of its own.** Its envelope is `{tag, links, meta}`, with `type` and `numItems` in `meta`. Clients learn tag versions from `format=versions`.
- **`meta` leaves out what does not apply.** `creatorSummary` is absent without creators, `parsedDate` without a date, and a child attachment's `meta` is `{}`. `numChildren` is always present. A summary reads `Smith`, `Smith and Myers` or `Ranganathan et al.`; `parsedDate` contains only the parts present, such as `2016` or `2018-05`.
- **A write response shows each object as it was just written.** A parent created in the same batch as its children reports the `numChildren` it had at that moment, as on zotero.org.
- **Error messages name the object**: `Item does not exist`, `Collection not found`, `Search not found`, `Invalid itemType 'bogus'`, `Invalid 'sort' value 'bogus'`.
- **An unreadable number is ignored.** `limit=abc` answers 200 with the default page size. Only a value the server understands and disagrees with, such as an unknown sort, is a 400.
- **Links to the first page omit `start=0`**: `?limit=2`, not `?limit=2&start=0`.
- **Field order decides whether an attachment can be saved.** The desktop processes an attachment's fields in the order they arrive, and fails if `filename` comes before `linkMode`. The failure is not reported once: the item is retried and fails on every later sync. altero therefore always serves fields in the schema's order — for an attachment `linkMode`, `title`, `accessDate`, `url`, `contentType`, `charset`, `filename`, `md5`, `mtime`, `note` — which is also the order zotero.org uses.

### Fields the published schema does not list

The published schema gives attachments only `title`, `accessDate` and `url`, and notes and annotations no fields at all. In reality an attachment also has `linkMode`, `contentType`, `charset`, `filename`, `md5`, `mtime` and `path`; a note has `note`; and an annotation has the `annotation*` fields. Validating strictly against the published schema would even reject the server's own `/items/new` template, so altero accepts these fields too. Any other field outside the schema is still refused, so a storage field on a book is an error.

If a write is refused with `Invalid field`, this is the first thing to check.

**`md5` and `mtime` are `null` until a file has been uploaded**, on attachments that store a file. A write that sends either as empty does not overwrite a stored value. The Android app depends on this: an empty string instead of `null` stopped it from ever uploading the file.

### Timestamps

`dateAdded` and `dateModified` come from the client and are stored unchanged, so uploading an existing library keeps its history. `serverDateModified` is always the server's own time, so no client can reorder results by changing its own clock.

### Citations and bibliographies

zotero.org sends items to a separate citation server. altero formats citations itself, with [citeproc-py](https://github.com/brechtm/citeproc-py) and a packaged copy of the Citation Style Language styles ([citeproc-py-styles](https://github.com/inveniosoftware/citeproc-py-styles)). Nothing is fetched while answering a request, so an instance without internet access can still use every published style.

**Items are mapped to CSL the way Zotero maps them**, using the tables in Zotero's own schema. A schema update therefore changes the output with it.

**`format=csljson` always wraps items** in `{"items": [ ... ]}`, even a single one, as zotero.org does.

**`format=bib` is one document.** It carries `Total-Results` but no `Link` header, refuses `sort`, `direction`, `start`, `limit` and `order` with a 400, and holds at most 150 items.

**`include` is checked.** `data`, `bib`, `citation`, `csljson`, `none` and every export format are accepted. `include=none` cannot be combined with anything, `include` outside `format=json` is a 400, and so is an unknown value. zotero.org also accepts `html`, which needs Atom and is requested through `content` here.

**Every export format zotero.org offers is available.** zotero.org runs Zotero's JavaScript translators; altero has a Python port of each of the sixteen formats, checked against what zotero.org returns for the same item:

- Refer/BibIX, RefWorks Tagged, Wikipedia citation templates, COinS, MODS and TEI match byte for byte.
- CSV and EndNote XML match except for one deliberate difference each, listed below.
- The three RDF formats match statement for statement, apart from whitespace.
- BibTeX, BibLaTeX and RIS are produced from the item's CSL data instead of ported. Nothing these formats can hold is lost, but a type CSL calls `document` becomes `@misc` or `GEN`. Citation keys are author, year and the first significant title word, with a letter added where two collide; a `citationKey` field on the item always wins. Tags become keywords.

Like Zotero, altero hands the TEI translator the item exactly as the API serves it, and every other translator the older field names they expect.

Eight deliberate differences in the exported files. The first names the program that wrote the file; the rest avoid copying something broken:

- **Files say altero wrote them**, in EndNote XML and Evernote, where zotero.org's name Zotero.
- **XML and RDF files match in content, not whitespace.** No XML or RDF reader can tell the difference.
- **CSV's `Date Added` column holds the date added.** zotero.org writes the date modified there.
- **Bookmarks are escaped**, so an ampersand in a title no longer produces a file HTML readers misread.
- **Evernote escapes ampersands once**, not twice, so a title with `<` no longer reads `&lt;`.
- **An Evernote `<updated>` ends in one `Z`**, and an item without a URL has an empty `<source-url>` instead of the text `undefined`.
- **An ISBN field holding two numbers separated by two spaces gives two Bibliontology entries**, not two plus an empty one.
- **TEI entry ids:** when two entries would get the same `xml:id`, the second gets the letter, because a file written in batches cannot go back and rename an entry already sent.

Exports over the API carry neither attached files nor child notes, on either server: each item is exported on its own. Whether a format writes anything for a note, attachment or annotation is left as Zotero's translator decides.

Three differences in formatted citations:

- **Old style names still work.** The API's default style, `chicago-note-bibliography`, was renamed years ago; altero follows the CSL project's list of renamed styles. An unknown style answers `404 Style not found`.
- **A style given as a URL is refused** with `400 Invalid style`. zotero.org fetches it, but fetching any URL on request would turn the server into a proxy for anyone holding a key.
- **Hanging indents and line spacing are written as zotero.org writes them**, but the alignment some numbered styles use for their numbers (`second-field-align`) is not reproduced.

One known flaw comes from citeproc-py: a label can appear for a value the item does not have. In the API's default style, an in-text citation of an item without an edition ends in a stray `edition.` Bibliographies in that style are fine, as are citations in APA, MLA, IEEE, Nature, AMA and the other Chicago styles. The fix has been reported upstream.

### Item type schema

These came from comparing all 163 schema responses with the live API.

- **`/itemTypes` and `/itemFields` are sorted by their translated names**, so the order changes with `locale`. Sorting is by character code, so *Software* (`computerProgram`) sorts under S and *TV Broadcast* comes before *Thesis*.
- **`/itemTypeCreatorTypes` lists the primary creator type first**, then the rest by translated name.
- **`/itemFields` leaves out base-only fields** such as `medium` and `authority`. They are still accepted in writes.
- **Two templates disagree with the schema.** For `videoRecording` and `radioBroadcast` the schema calls `creator` the primary creator type, yet `/items/new` fills those templates with `director`. altero reproduces both, so a template from altero is interchangeable with one from zotero.org.

## Files and synchronization

### The file protocol

Uploading a file takes three requests — authorize, send the bytes, register — exactly as with zotero.org, including the `uploadKey` passed between them and the `{"exists": 1}` answer when the server already holds those bytes.

The middle step differs. zotero.org hands the client an Amazon S3 address plus a `prefix` and `suffix` to wrap around the file. altero points back at itself and leaves both empty, so the client sends the file as it is. A client that wraps the file as documented still sends exactly the file.

**The mobile apps ask for a form.** The iOS and Android apps add `params=1` and then send the file as a form upload. altero answers that request shape too, with empty form fields, and accepts the file from a form or as a plain body.

**Stale uploads are refused.** Bytes are checked against the declared MD5 and length, and `If-Match` or `If-None-Match` is required, so a client working from outdated information cannot overwrite a newer file. A conflicting upload answers 412 with `Last-Modified-Version` set to the attachment's own version; the desktop uses that header to open its file-conflict dialog. Without it, two desktops racing to upload kept retrying instead of resolving the conflict.

**A file is stored whole or not at all.** An upload that stops part way — a full disk, a dropped network mount — leaves no file rather than a short one. That matters because files are stored by content: a damaged file would be reported as `{"exists": 1}` to every later client holding the same bytes, and each would mark its attachment as synced for good.

Registration therefore checks the stored file against its digest before attaching it. A file that is not what was sent is removed and the registration refused; the client treats that as a file-sync error and sends the file again on its next sync. One mismatch is not damage: two clients zipping the same snapshot produce different archives, so the stored archive may be somebody else's. The registration is still refused, but an intact archive stays (see [Racing ZIP archives of different sizes](#racing-zip-archives-of-different-sizes)).

**An attachment can claim a file the server does not have.** A library moved from zotero.org whose files were kept on WebDAV names a digest for every attachment, but none of the files. So `If-None-Match: *` ("is there a file to protect?") is answered by looking for the file itself, not at what the attachment claims; otherwise the upload that would repair the attachment is refused. `If-Match` is still checked against the attachment, because that is how the client proves it is not working from stale information.

#### Downloading is a redirect, and has to be

Asking for an attachment's file answers **302**, with three headers:

| Header                          | What it says                                             |
|---------------------------------|----------------------------------------------------------|
| `Zotero-File-Modification-Time` | the modification time the uploading client declared      |
| `Zotero-File-MD5`               | the digest the attachment claims                         |
| `Zotero-File-Compressed`        | `Yes` when the stored bytes are a ZIP around that file   |

The desktop reads these headers from the redirect and nowhere else. Answering 200 with the bytes makes every download fail with "A file sync error occurred". The redirect also lets the client skip the download entirely when the modification time shows its copy is current.

##### The location has to be a credential

The desktop does not follow the redirect itself. It reads the headers, then makes a *new* request to the location, sending no API key with it. zotero.org can do that because its location is a pre-signed S3 address, which is a credential in itself.

So altero's location is one too: a short-lived permission for that one file, at `/storage/download/<key>`. It expires after five minutes, is valid only for the file the redirect described, and is marked so that no shared cache stores it. It can be used more than once, because the desktop retries the same address after a server error or a dropped connection.

The location is a full URL, because the desktop accepts nothing else here.

Appending the caller's API key to the location (`?key=…`) would also work, and was rejected. An API key grants the whole account and never expires, and reverse proxies write every requested address into their access logs.

> [!NOTE]
> Before Zotero's April 2026 rewrite the desktop followed this redirect itself and sent its key along. The older location, `<prefix>/items/<key>/file/content`, is still served for callers with a key that want the bytes directly.

#### Telling an archive from a file

The desktop zips a web snapshot before uploading it. If a download then says `Zotero-File-Compressed: No`, the client saves the ZIP itself under the attachment's name, and the snapshot is quietly lost.

altero needs no stored flag to tell the two apart. A stored file whose content does not match the digest it is filed under is an archive around the real file. Only files that start like a ZIP are checked, and a `.docx` or `.epub` — which are ZIPs themselves — matches its own digest and is served as it is. Each archive is checked once, not on every sync.

## Authentication and client login

### Obtaining a key

To link an account, the desktop creates a login session (`POST /keys/sessions`), opens the `loginURL` it receives in a browser, and polls the session until the response carries `apiKey`, `userID` and `username`, alongside `displayName` and `emails`. None of these fields is in the published documentation; they were found in the client source, and altero sends all of them.

At zotero.org the browser window signs in to zotero.org. Here it opens altero's own interface, which asks the signed-in person to confirm and then issues the key. The client sees the same exchange either way.

**Confirming takes a fresh proof of identity**: the password, or, for an account without one, signing in again at its identity provider within the last five minutes. What is handed over is a full-access key that outlives the browser session, so an already open tab should not be able to approve it just by visiting a link.

**Usernames and email addresses are separate**, as at zotero.org. A username may not contain `@`, because signing in accepts either and decides which by the shape of what was typed. An account holds at most one address, reported only once confirmed.

**Changing a username does not unlink a client.** The client identifies an account by its numeric `userID` and accepts a changed username silently.

**`loginURL` carries a query**, as zotero.org's does. The Android app appends `&app=1` to it as text; without an existing query that landed in the path and the app opened a 404 page.

The command line still works, and is the way in when the web interface has not been built: `loginURL` then shows the `altero login approve` instructions.

**A re-authentication for one account cannot be approved for another.** Handing a client somebody else's key makes it warn, offer to reset its data directory and quit. The confirmation screen says so before offering a button, and the server refuses it anyway.

**The key covers group libraries too**, as zotero.org's does. A key without group access makes the client think the server has lost the groups.

`POST /keys` (a key from a username and password) is not implemented. The client only uses it when migrating a profile that still holds a sync password from before 2016.

**Managing keys was never part of the v3 API.** `/users/<id>/keys` exists at zotero.org but only answers zotero.org's own signed-in web pages; an API key gets 403. altero offers the same under **Settings → API keys** in the browser, plus `altero key add` and `altero key revoke`. An API key can do to itself what zotero.org allows: read `/keys/current` and delete itself.

### A credential that gave up notes or files

A credential says four things about a library: whether it may read it, write to it, read its notes, and download its files. An API key carries them as `library`, `write`, `notes` and `files`; an OAuth token as the scopes `library.read`, `library.write`, `notes.read` and `files.read`. Notes and files only ever narrow reading: without read access there are no notes or files either.

**A hidden note is hidden completely.** Without note access, a note answers 404 by key and is missing from every listing, export, key list and version list. `numChildren` does not count it, and a tag carried only by hidden notes disappears from item-scoped tag lists. This is what zotero.org does. Serving the note with its text blanked would tell the caller it exists.

**Without file access, only the bytes are refused.** The download endpoints answer 403, but the attachment itself — with its `md5`, `filename` and `contentType` — is still served.

Two rules from zotero.org that are not guessable:

- **An anonymous reader of a public library can read its notes but not its files.** In a public group, *only members have file access*.
- **A credential never sees less of a public library than a visitor with no credential at all.** Notes in a public library are readable whatever the credential says. Files are not, for the reason above.

**File access does not cover the full text.** A credential that may read the library may read an attachment's extracted text, even without file access — as on zotero.org. The consent screen's *Download your attachments* is about the files themselves.

Two deliberate differences:

- **The restrictions apply to group libraries too.** zotero.org applies them only to the personal library. A consent screen that says *Read your notes* should mean it everywhere.
- **Uploading depends on write access, not on file access.** At zotero.org one `files` permission covers both directions. Here it is named for downloading, and the consent screen says *Download your attachments*, so it does not also grant uploads. Write access and the group's file-editing setting decide who may upload.

None of this changes what the desktop sees: the keys it receives, and every key made in the browser or on the command line, carry all four permissions. Only an OAuth token can lack them.

### What the desktop client actually sends

These were found by running the real client, not by reading the documentation.

**`mtime` is in milliseconds and needs a 64-bit number.** PostgreSQL refused it in a 32-bit column, so uploads worked in development on SQLite and failed in every container deployment.

**`mtime` is served as a number**, as on zotero.org, although every other field is a string. The desktop requires a number when it resolves a file conflict in favor of the local copy.

**Full text is uploaded in batches.** The documentation describes `GET`/`PUT` on one item's full text, but the client uploads with `POST <prefix>/fulltext`, carrying a list of entries and requiring `If-Unmodified-Since-Version`. Each entry reported back must be an object with a `key`, not a bare key.

zotero.org advances the library version once per item in the batch; altero once per request. The client cannot tell the difference, because it only uses the final version.

**Recreating a deleted setting clears its deletion record**, as on zotero.org. The desktop downloads settings before deletions, so a leftover record for `tagColors` would throw away the colors it just downloaded.

**Tag deletions arrive without naming the tag.** Because of a quirk in the client, `DELETE <prefix>/tags?tags=a||b` reaches the server as a bare `DELETE <prefix>/tags`. zotero.org answers 204 having deleted nothing, and the client accepts only 204 or 412 here, so altero answers 204 too. It also understands `tags=a||b` in case the client ever stops dropping it.

**Uploads are compressed.** The client gzips large request bodies, including full-text batches, which the documentation never mentions. altero decompresses them first; a body that does not decompress is a 400. Because this happens before authentication, compressed bodies and what they expand to are both limited to 128 MiB (413 beyond that). The client's largest write — 50 notes at zotero.org's length limit — is about 100 MB.

**Snapshots arrive as ZIPs, with two digests.** `md5` describes the original file and `zipMD5` the archive actually sent. altero checks the transfer against `zipMD5` and records `md5` on the item, which is what the client sends back next time.

**The upload address must be a full URL.** The client refuses a bare path.

**Uploads are changes, not whole objects.** After the first sync the client uploads only what changed — for example `{key, version, lastRead, dateModified}` with no `itemType`. A batch entry naming an existing item without `itemType` is therefore a partial update. A new item must still state its type. See [A POSTed batch is a batch of patches](#a-posted-batch-is-a-batch-of-patches).

**Registering a file upload advances the library version.** The full-text upload that follows can then arrive with an outdated version and get 412. The client syncs and retries successfully — one wasted round trip. zotero.org does the same, and not advancing the version would hide file changes from anyone asking what changed `since`.

**A client may be ahead of the server.** If the client's library version is higher than the server's, the write is accepted, as on zotero.org. zotero.org never gets into that state, but altero can, when a database is recreated while a client remembers a later version. The client then refuses the server's answer ("cannot decrease"), and re-uploads the same objects on every sync. "Restore to server" fails the same way. The only way out is to raise the server's counter above what the client remembers, with `altero library set-version`. Objects the client believes are already synced are not uploaded again, so anything written before the reset can be missing afterwards. Neither the check nor the answer is changed to avoid this: both are zotero.org's.

**Two services the client uses are not part of the dataserver.** `GET /retractions/list`, which flags retracted papers, answers 404. An empty list would claim that nothing in the library has been retracted, which altero cannot know. The client logs the failure and syncs normally. The streaming API is served — see below.

**Pointing the client at altero does not redirect its streaming connection.** The streaming address is set separately, by `extensions.zotero.streaming.url`, and defaults to `wss://stream.zotero.org`. A client configured only with altero's API address therefore opens a connection to zotero.org and sends it the API key — a full-access credential handed to a third party, though zotero.org rejects it as unknown. The symptom is a log line: `WebSocket connection closed: 4403 Invalid API key`. Set `streaming.url` to altero's own endpoint, as [Clients](clients.md) describes; `extensions.zotero.streaming.enabled = false` also stops it.

[streaming]: https://www.zotero.org/support/dev/web_api/v3/streaming_api

### The streaming API

Served at `/stream`, not on a separate host, and the client is pointed at it with `extensions.zotero.streaming.url`. It follows the [published protocol][streaming]. Both ways of subscribing work: an API key in the handshake, and `createSubscriptions` naming a key and no topics, which is what the desktop sends.

**Three topics that are not libraries** are accepted, because the client asks for them on every connection:

- **`styles` and `translators`** are accepted but never fire; the client updates those on its own schedule.
- **`login-session:<token>`** tells the client the moment a login is approved, instead of at its next poll. It needs the session's token, and on approval it carries the same body the poll returns. An approval from `altero login approve` on the command line is not announced; the client's poll finishes the login as before.

**Removing a subscription that does not exist is ignored**, instead of closing with 4409. The client's login flow does exactly that, and treats an unexpected close as its own error and stops reconnecting.

**`subscriptionsDeleted` names what was removed**, which the client needs.

**Guessed rather than copied**, since there is no reference implementation:

- Close code **4400** for a message that is not JSON or asks for something unknown, continuing the documented 4403, 4409 and 4413.
- At most **50 subscriptions per connection**. The documentation says a limit exists but not what it is; the desktop holds one.
- **`topicAdded` and `topicRemoved`** go only to subscriptions that named no topics. A client that chose its topics is not given new ones.

**An event is sent only once its write is committed.** A client told about a version that was then rolled back would ask for it and find the library older — indistinguishable from a server that went backwards.

**One process only.** Events are passed around in memory. With several worker processes, a client hears only about writes handled by its own worker; the others fall back on polling, as before.

### Atom

`format=atom` is served for items, collections, saved searches and tags, both for lists and single objects. `content` chooses what goes inside: `html` by default, or `json`, `bib`, `citation`, `csljson`, an export format, `none`, or several at once. The shapes were copied from zotero.org.

Five differences, most following from decisions elsewhere on this page:

- **No `rel="alternate"` links.** See [Deliberate differences](#deliberate-differences).
- **`<id>` uses the address the request came to**, not `zotero.org`.
- **Feed titles start with `altero`**, not `Zotero`. The rest of the wording is zotero.org's.
- **No `rel="first"` link on the first page.** The feed's links and the `Link` header come from one place, so they cannot disagree.
- **The HTML table lists fields in the item's own order.** zotero.org orders them by an internal number the published schema does not include.

A `<content>` element carries both `zapi:type` and a media type, so readers looking for either find it. A bibliography that is not valid XML is escaped and marked as HTML, so one bad entry cannot make the whole feed unreadable.

`content` is refused outside `format=atom`, and a citation is refused for collections, saved searches and tags: an empty answer would look the same as an object without one.

### API versions

Only version 3 is served. Asking for another version, by the `Zotero-API-Version` header or the `v` parameter, is a 400: older clients expect different envelopes, parameter names and pagination, and version 3 answers under an older label would be worse than a refusal. A header and a parameter that disagree are refused too, as on zotero.org.

### The `relations` map

A relation with one target is a **string**; with several it becomes an **array**. Zotero relies on this — an item related to three others names all three under `dc:relation` — so the shape matters.

Collections carry relations too, and they are stored like items' relations.

An empty array is accepted in place of an empty object, as zotero.org allows.

Not copied: zotero.org accepts only certain relation types and requires Zotero addresses as values. altero accepts any. That is the permissive direction, so no client breaks, but a library moved from altero to zotero.org could carry a relation zotero.org refuses.

### Backoff and Retry-After

The desktop ignores both headers unless they are **whole seconds**, and `0` is as useless as a fraction. Without `Retry-After`, a 429 still works, but the client has to guess how long to wait.

altero answers 429 with a whole-second `Retry-After` of at least 1. It does not send `Backoff`, which asks clients to slow down while still being served; that needs a measure of load altero does not have.

On SQLite, a write that waits more than five seconds for another write to finish answers **503 with `Retry-After: 5`**. Nothing has been written at that point. The desktop retries such a 503 and would report any other server error as a sync error. PostgreSQL waits instead and never gives this answer.

## Libraries, groups and altero extensions

### My Publications

`/users/<id>/publications/items` can be read **without a key**, as on zotero.org. Only items marked `inPublications` appear, in `items`, `items/top` and by key; any other key answers 404, so an item hidden from the list cannot be fetched directly either.

`publications/collections` and `publications/searches` answer 404, as on zotero.org. Nothing can be written here: an item joins the list by being saved in the library with `inPublications` set.

There is no group version. My Publications belongs to a person, which is also why `inPublications` is refused on a group item.

`publications/settings` and `publications/deleted` are served and always empty, because the client polls both and treats anything but 200 as a failed sync.

zotero.org also answers `publications/settings` with a 400 — "Please upgrade to the latest Zotero 5.0 beta" — once a user has published anything. That was a temporary guard for an old kind of publications library that altero never had. Copying it would refuse every current client that has published something.

#### Who may read My Publications

At zotero.org anybody can. altero keeps that as the default and lets each account narrow it, because a personal server is not a public service — see [Sharing](web/sharing.md#who-can-see-it). The setting applies to the API as well as to the profile page:

| Setting            | No key | Any key from this server | A key that may read the library |
|--------------------|--------|--------------------------|---------------------------------|
| `public` (default) | 200    | 200                      | 200                             |
| `users`            | 403    | 200                      | 200                             |
| `private`          | 403    | 403                      | 200                             |

The last column is why the owner's desktop keeps syncing: its key may read the library, so closing the page never breaks the sync that fills it. Every publications endpoint applies the setting, including the `settings` and `deleted` polls. An instance that never changes the setting behaves exactly like zotero.org.

#### Profile pages

zotero.org's profile page is `zotero.org/<name>`, with the username simplified for the address. altero serves the same page at `/app/u/<username>`. The prefix keeps a username such as `settings` from colliding with the interface's own pages. Both the username and zotero.org's simplified form work, in any letter case.

The heading shows the real name, or the username when there is none. There is no link to zotero.org, for the same reason as everywhere else.

#### Publishing from the browser

The API knows only the `inPublications` flag, but publishing is more than that. Before setting it, the desktop asks four questions: whether files go along, whether notes go along, whether an existing **Rights** value stays, and which license the work is published under. altero's browser interface asks the same four and follows the desktop's rules:

| Rule                                                                                       |
|--------------------------------------------------------------------------------------------|
| Child notes go along only when chosen                                                      |
| Stored files go along only when chosen                                                     |
| Links to web pages always go along                                                         |
| Linked files never do, because the server does not hold them                               |
| Annotations never do                                                                       |
| The license is written into **Rights** unless an existing value was chosen to stay         |
| Removing an item takes its notes and attachments with it, including trashed ones           |
| Removing something that is not published is an error                                       |

These requests belong to the browser interface and cannot be made with an API key.

Three deliberate differences:

- **The license name is written in English**, whatever language the account uses. The desktop writes the name in the language of its own window, so the same license reaches the field in German from one client and in English from another. **Rights** is data that gets exported and cited, not a label, so it should not depend on who published.
- **The license can be changed afterwards.** The desktop never shows its wizard twice for an item; a different license is typed into the **Rights** field. The browser has no field editor, so it allows editing **Rights** and nothing else. The edit is refused if the item changed in the meantime.
- **The generic "Creative Commons" choice is not offered.** It is what the desktop reports while a license is still being chosen; here, choosing Creative Commons always leads on to the two questions that pick one of the six licenses.

### Trashing a collection or a saved search

Zotero trashes collections and saved searches by marking them `deleted`, and syncs that mark like any other property.

**Trashed collections and searches stay in the listings**, marked `deleted: 1`, because the client has no way to ask for trashed ones separately. Hiding them would tell the client they were gone, not trashed.

Their counts follow zotero.org, and differ: `numCollections` includes trashed subcollections, `numItems` leaves out trashed items.

Items are unaffected: they have their own trash endpoint, and `/items` still leaves trashed ones out.

The value must be `true`, `false`, `0` or `1`; otherwise the string `"false"` would count as trashed.

### `inPublications`

An ordinary item property. Setting it to true is refused in three cases:

| Refused                        | Message                                                              |
|--------------------------------|----------------------------------------------------------------------|
| A group library                | `Group items cannot be added to My Publications`                     |
| A top-level note or attachment | `Top-level notes and attachments cannot be added to My Publications` |
| A linked-file attachment       | `Linked-file attachments cannot be added to My Publications`         |

Child notes and attachments are allowed; that is what My Publications is for. A linked file is not, because the server does not hold the file.

The property appears only when true, as `deleted` does.

**A partial write that leaves it out leaves it alone**, and the same goes for `deleted`. So changing an item's title does not take it out of the trash or out of My Publications. A `PUT` still clears what it leaves out; the client always sends `deleted: false` explicitly when restoring.

Reading the public list is described under [My Publications](#my-publications); publishing with the desktop wizard's options, under [Publishing from the browser](#publishing-from-the-browser).

### A POSTed batch is a batch of patches

In a `POST` to `/items`, `/collections` or `/searches`:

- an entry naming an object that **exists** may leave out anything it is not changing, and what it leaves out stays as it was;
- an entry for a **new** object must still contain what a new object needs: a collection its name, a saved search its conditions, an item its type.

`PUT` replaces the whole object: what it leaves out is cleared.

**An entry with a version above 0 must name an existing object.** If the object is gone, that entry fails with 404, even if it is complete. The desktop needs the 404 to settle an edit made against an object deleted elsewhere; recreating the object silently would undo the deletion. New objects use version 0 or no version.

This is the desktop's normal way of uploading: it remembers the last synced copy of each object and sends only the difference. Two common cases:

| The user did                   | What the client uploads         |
|--------------------------------|---------------------------------|
| Sent a collection to the trash | `{key, version, deleted: true}` |
| Changed an item's type         | `{key, version, itemType}`      |

Treated as complete objects, the first would be refused for lacking a name — stopping the whole library's sync — and the second would wipe every field, creator, tag and collection it did not mention.

**Leaving a property out means "unchanged"; sending it empty clears it.** That matters for the four list properties: `creators`, `tags`, `collections` and `relations`. The desktop really sends `collections: []` to take an item out of its last collection — for example after saving into a collection with the browser connector and then switching the save target to the library root. Treating empty as absent would leave the item filed, and the client would upload the same change on every sync forever.

An item without creators has no `creators` property at all, while `tags`, `collections` and `relations` appear even when empty. That inconsistency is zotero.org's and is copied.

### Objects that were sent again without changing

An object identical to the stored one is reported as `unchanged` and keeps its version, as on zotero.org. Saving it again would advance the library version and make every other client download an object that never changed.

Everything a client can set counts as a change: type, fields, creators and their order, relations, parent, trash flag, `dateAdded`, `dateModified`, tags and collections. The server's own values — the version and `serverDateModified` — do not. A batch in which nothing changed leaves the library version as it was.

Settings follow the same rule: a setting is changed only if its value differs, so `3` and `3.0` differ but `3` and `3` do not. A request that changes no setting answers 204 with the library version unchanged; in a batch, only the settings that changed get the new version.

The current dataserver advances the library version for each object in a batch, even an unchanged one. altero advances it once per request that changes something. Object versions and the reported results still agree; only the library's version number can differ between the two servers.

Two places skip this check, as on zotero.org: a single-object `PUT` or `PATCH`, which has no report to put the answer in, and the full-text batch.

### Groups

zotero.org has endpoints for creating, editing and deleting groups and adding members, but only for its own administrators, in XML, and never used by the Zotero client. An ordinary key gets 403.

altero serves the same paths for ordinary users, with an **API key** and **JSON** in the shape `GET /groups/<id>` already returns, so what was read can be sent back. Inventing a separate administrator credential would have meant a second kind of credential on a server whose permissions are otherwise per library.

`PUT` replaces and `PATCH` updates, as for items. A `PUT` without a `type` makes the group private, the safe default. `POST /groups/<id>/users` adds a member by `userID` or `username`.

| To                                       | You need                                        |
|------------------------------------------|-------------------------------------------------|
| Create a group                           | a key that may write to your own library        |
| Read one                                 | membership, or a public group                   |
| Write items to one                       | membership, plus the group's editing setting    |
| Upload files to one                      | membership, plus the group's file setting       |
| Change its details, add or remove members | to be an administrator of the group             |
| Leave                                    | nothing but your own decision                   |
| Hand it over, delete it                  | to be its owner                                 |

Two of these are altero's own rules. A key must be allowed to write to the group *and* its owner must administer it, because adding items and deciding who else may are different things. Only the owner can hand over or delete a group, because both end it as its members know it.

**A key's "all groups" means the groups its owner belongs to**, never every group on the server.

Changing a group's details or its members advances the library's version. zotero.org keeps a separate group version; altero reports the library's for both. A role change therefore costs connected clients one sync that finds nothing new — the cheaper mistake, since a client that has not noticed a demotion still believes it may write.

#### Who the client finds in a group

**Group listings always carry a `Link` header**, even when empty or a single page. The desktop's account settings read it unconditionally and fail without it. zotero.org always includes an `alternate` link to itself; altero includes `self` instead. A page holds 25 groups by default; `format=versions` is unlimited.

A group's JSON lists `admins` and `members` as user ids, and the desktop needs them: it makes a group library editable for the owner, for administrators, and for members when the group lets members edit. Anyone found in neither list syncs the library read-only. The owner is in neither list, as on zotero.org, and empty lists are left out. The lists are read-only; membership has its own endpoints.

**Only members see the lists.** zotero.org shows them to anyone who can read the group, which for a public group is anybody. Nobody outside a group syncs it, so for a stranger the lists would only reveal who belongs.

The client fetches a group again only when its version changes, so every membership change advances it — from the API, the browser, the command line or an accepted invitation.

### Finer roles for one member

A Zotero group decides who may edit for the whole group at once: members or only administrators. Read-only members, members who may add but not remove, and members who may change only their own items have been requested on the Zotero forums since 2010 ([discussion 14053](https://forums.zotero.org/discussion/14053/)). altero has all three, as a **permission per member**, alongside their role.

A role says whether somebody helps run the group; a permission says how far they may go with its contents. An administrator can be an ordinary contributor, and a member can be limited to reading, without changing anybody's role.

| Permission | Creates | Changes  | Removes | Collections and searches      |
|------------|---------|----------|---------|-------------------------------|
| `inherit`  | ✓      | ✓       | ✓      | ✓                            |
| `read`     |         |          |         |                               |
| `add`      | ✓      | anything |         | make and change, never remove |
| `own`      | ✓      | its own  | its own | read-only                     |

Four decisions shape it:

- **It only ever restricts.** It is applied last, after the key's permissions, membership and the group's own editing setting. A member marked `add` in a group where only administrators edit still cannot edit.
- **Moving to the trash counts as removing**, because that is how the desktop deletes. Otherwise a member who may not delete could still empty the library. Restoring from the trash is allowed.
- **The shared structure belongs to nobody.** Nothing records who made a collection, saved search or setting, so `own` treats all of them as somebody else's. Filing your own item into a collection is a change to the item and is allowed: contributors put their work where the group's structure says, but cannot restructure it.
- **Administrators cannot be restricted.** They can edit any membership, including their own, so a restriction would be shown but not enforced. Making somebody an administrator clears theirs.

#### One library version, two representations

`read` is the only permission Zotero clients already understand: a read-only member is told the group's editing setting is "administrators only", while everybody else sees the real setting. The client then shows the library read-only, as it does for any member of such a group.

So the same library version looks different to different people. That is sound, because a group never had one view for everyone — a stranger gets 404 where a member gets 200 — and a member's view changes only when the library's version does, which changing a permission causes.

#### `add` and `own` surface as sync errors

Zotero clients have no way to show these two, and altero does not invent one. A restricted member's desktop shows the library as editable, and a forbidden write comes back as **403** with an explanation:

- `You can add to this group library but not remove from it`
- `You can only change what you added to this group library`
- `You can only remove what you added to this group library`

The desktop shows this as a sync error, and the sentence is the only explanation the member gets. Anyone setting `add` or `own` should know that is how it looks from the other side. The browser interface knows both permissions and hides what they forbid.

#### Where a permission is set

In the browser on the group's member list; in an invitation, so that "come and read this" and "come and help" are different invitations; with `altero group permission <group> <username> <permission>`; or through the API with `PUT /groups/<id>/users/<userID>`, which takes `permission` alongside `role`. When both are sent, the role is applied first, so a demotion followed by a restriction ends with the restriction.

### Renaming a tag

`PATCH <prefix>/tags/<name>` with `{"tag": "<new name>"}` renames a tag and answers 204 with the new `Last-Modified-Version`.

zotero.org has no such endpoint: renaming is left to the client, item by item, and has been requested since 2016 ([dataserver#108](https://github.com/zotero/dataserver/issues/108)). So the endpoint is altero's own, and its behavior is copied from the desktop's own rename:

- **Both kinds of tag are renamed.** A name can belong to a manual tag and an automatic one at the same time; both are renamed, just as deleting a tag deletes both.
- **Exactly one tag is left under the new name**, carrying every item that had either name — including an automatic tag that already had the new name.
- **The renamed tag is manual.** Renaming is how an automatic tag stops being one, in the desktop too.
- **Items already carrying the new name are left alone**, and an item that carried both names ends up with it once.
- **Every affected item gets the new library version**, so other clients download it. Their `dateModified` stays as it was, because no client made that change.
- **The old name is recorded as deleted**, as if it had been deleted, and any deletion record for the new name is cleared. Otherwise one sync could tell a client both "remove this tag" and "here are items with it".

`If-Unmodified-Since-Version` is required. Renaming a tag to its own name changes nothing and does not advance the library version. An unknown tag is a 404; an empty name, or one longer than 255 characters, is a 400.

The browser's tag list uses the same rename — see [Tags](web-interface.md#tags).

### The desktop client's three extra views

The desktop's sidebar shows **Recently Read**, **Duplicate Items** and **Unfiled Items**, all worked out from its local copy of the library. zotero.org's API has none of them, so altero's versions exist only in its browser interface; the v3 API is unchanged.

**Unfiled Items** needs no interpretation: top-level items in no collection and not in the trash.

**Duplicate Items** is a judgment. Two items count as the same work if they share a DOI or ISBN (ignoring punctuation, case and any `https://doi.org/` prefix), or if they share a title (ignoring punctuation and case) *and* a creator surname or year. A title alone is not enough, because many works are called "Introduction"; only when neither item has a creator or a year does the title stand alone. Item types are not compared, so a book and a chapter of it appear as a pair. Notes, attachments and annotations are never compared.

**Recently Read** is a guess. Zotero 7 records when an attachment was last read and syncs it, but which items the desktop lists, and over what period, is not documented. altero lists items whose attachments were read in the last 90 days, newest first where the sort allows, and stand-alone attachments themselves. **The 90 days is a guess**, chosen so the view does not grow into "everything ever opened".

### Reading a library out of zotero.org

This is the one place altero makes requests instead of answering them: it reads a personal library from api.zotero.org and turns it into the same archive `altero library export` writes, then restores that archive.

**It needs an API key.** zotero.org offers no password sign-in for software, and OAuth would require every altero instance to register with Zotero. The key is used for the import and then forgotten.

**Three things zotero.org's API does not provide**, and what altero uses instead:

| Missing                                       | Instead                                                                                                  |
|-----------------------------------------------|----------------------------------------------------------------------------------------------------------|
| `serverDateModified`                          | The item's `dateModified`, which is the same moment for anything a client last wrote                      |
| Dates for collections, saved searches and tags | The time of the import                                                                                   |
| Versions of deleted objects                   | The library's current version, so a client asking what was deleted since any earlier point hears about all of it |

**Links between items are rewritten to the new account.** Related items, merge records and similar links name the account they belong to as `http://zotero.org/users/<id>/items/<key>`. The account number is changed to the new one, or every link would point to an account this server does not know. The `zotero.org` part stays, because the desktop recognizes these links only in that exact form. Links into group libraries are left as they are, since groups are not imported.

**zotero.org's rate limits are obeyed** the way the desktop obeys altero's: requests go one at a time, `Backoff` pauses before the next request, and a 429 waits as long as `Retry-After` says — or, without it, a doubling delay starting at one second.

**`/tags?format=versions` fails on api.zotero.org** with a server error, for every library tried, including Zotero's own example account. A real import stopped on it after reading everything else. So the import treats only items, collections and saved searches as essential and stops if one cannot be read. Tag versions, settings, full text, the deletion log and attachment files are read if possible and listed in the report if not. A tag without a version gets the library's, which is the safe direction: clients asking what changed hear about it.

**Pages are fetched by position**, not by following the `Link` header, because that header always points at api.zotero.org.

## The authorization server

### A second credential for the v3 API

The v3 API is authenticated by a credential sent with each request, **never** by a browser cookie. The authorization server lets an OAuth access token be that credential, alongside an API key; the rule itself is unchanged.

That distinction is the whole reason it is allowed. A browser attaches cookies to requests any website can trigger, so a cookie that worked on `/users/<id>/items` would expose the entire sync protocol to cross-site attacks. A token is sent only by the application holding it, and no other website can make it be sent.

`/keys/current` and `/keys/<key>` refuse access tokens. They describe and revoke an API key; a token is not one.

### Confining a grant to particular resources

A scope says *what* an application may do, never *where*. `library.read` means the whole personal library and `groups.read` every group the account belongs to — usually more than an application needs. On the consent screen the account holder can therefore narrow a grant to particular libraries, or to particular collections in them: "group 42 and none of my others", "the *Reading* collection and nothing else".

zotero.org has nothing like this, so there is nothing to copy, and API keys are unaffected. Grants made before this feature existed stay unrestricted.

**A collection means the branch**: everything nested inside it, at any depth, and anything filed there later — as with shared links and the desktop's *Show Items from Subcollections*. Otherwise filing a paper into a subcollection would quietly withdraw it from the application. Granting a subcollection does not grant its parent.

**What a collection grant reaches**: items filed in the granted collections, plus their notes, attachments and annotations — child items are never filed in collections themselves, and a paper without its PDF would be useless. Nothing else: an unfiled item is outside, and so is an item filed only elsewhere, with its children.

**Refusals reveal nothing.** A collection outside the grant is absent from every listing and answers 404 by key, and so does an item inside one — directly, through its children, its file, its full text, or a write naming it. 404, not 403, so an application cannot map the parts it was kept out of by guessing keys. A whole library that was not granted answers 403, since the caller already named it. Renaming tags, deleting saved searches and deleting settings answer the same way, so they cannot be used to probe for names either.

**My Publications keeps its notes.** Published items can be read with no credential at all, so a confined token still sees their notes — but only the published items inside its grant, which is less than an anonymous visitor sees and the right way round.

**Four things a confined grant never gets**, because they belong to no collection:

- **Saved searches.** A saved search reaches wherever its conditions reach. `/searches` answers with an empty list.
- **Settings**, such as tag colors. `/settings` answers with an empty object.
- **The deletion log.** A deleted object no longer says which collections it was in, so there is no way to tell whether it was inside the grant. `/deleted` reports nothing.
- **Changing the library's structure**: no creating, renaming or deleting collections, no saved searches, no settings, no tag renames (a rename changes items outside the grant too), and no group changes or new groups. Items inside the grant stay writable if the scopes allow it.

An item can be moved between granted collections but not out of them, and a new item must be placed in a granted collection.

`GET /users/<id>/groups` lists only granted groups, and the `groups` claim in user info and ID tokens is narrowed the same way.

**The restriction belongs to the grant**, not to a token, so a refreshed token keeps it; otherwise an application could simply wait for it to expire. Deleting the last collection a grant named leaves it reaching less, never everything.

### Signing ID tokens while still not verifying them

These two decisions look contradictory, but are not.

As a *client* of somebody else's identity provider, altero does not verify the signature on the ID tokens it receives — see [below](#not-verifying-the-id-tokens-signature). As an *identity provider*, it signs the ID tokens it issues (RS256), publishes its key at `/oauth/jwks.json`, and checks its own signature when a token comes back during sign-out.

Every reason for not verifying other providers' tokens concerns input somebody else controls: a token claiming no algorithm, confusion between key types, a key chosen by the attacker. Signing its own tokens and checking them against its own keys involves none of these: the algorithm is fixed and no key is looked up from the token. The implementation is tested against the published examples in the relevant standards (RFC 7515 and RFC 7638).

### No dynamic client registration

Applications cannot register themselves (RFC 7591), and never will. The list of addresses an authorization code may be sent to is the whole security of the sign-in flow; a list anyone can add to protects nothing. An administrator registers applications from the command line.

### PKCE is required, and `S256` is the only method

The `plain` method makes the challenge identical to the secret it protects, so anyone who intercepts the code has everything needed to use it. altero neither offers nor accepts it, and requires PKCE from every application, including those with a client secret.

### Scopes are refused rather than narrowed

An unknown scope, a scope the application is not registered for, or one useless without another is an error, rather than being quietly dropped. Dropping it would produce an application that half works and a person who cannot tell which half. `library.write` without `library.read` is the useless case.

There is no `annotations.*` scope: annotations are items, and the API has no separate permission for them.

## Identity-provider security notes

### Not verifying the ID token's signature

Not a compatibility question — zotero.org has no single sign-on — but recorded here because it looks wrong and is deliberate.

altero does **not** verify the signature on OpenID Connect ID tokens. It fetches the token itself, directly from the provider's token endpoint over TLS, and the OpenID Connect standard (Core §3.1.3.7, item 6) allows the TLS connection to vouch for the token in exactly that case. Not verifying keeps a signature implementation out of altero, along with its classic mistakes, and altero never reads the token's header, so there is nothing there to forge.

This rests on two conditions, both always true here:

- **altero is a confidential client.** It sends a secret with the token request and uses the authorization code flow with PKCE only.
- **The token comes from the token endpoint**, never from the browser.

Every claim is still checked — issuer, audience, authorized party, nonce, expiry, issue time and subject — and with no signature check, those checks are where the security lies.

**Supporting public clients would require revisiting this first**, since the exemption does not cover them.

### Reading a SAML assertion out of what was signed

The code looks as if it does less than it should, which is why this is written down.

Signature verification is left to the [signxml](https://github.com/XML-Security/signxml) library; writing it by hand is where implementations grow security holes. The defense against forged assertions is structural: altero reads every claim from the part of the document the library confirmed was signed, never from the document as received. An attacker who wraps a forged assertion around a genuine one still gets only the genuine one read.

A valid signature still proves nothing on its own, so altero also checks:

| Check                       | Why a signature does not cover it                 |
|-----------------------------|---------------------------------------------------|
| The status is success       | A failed sign-in is signed too                    |
| The validity period         | An assertion from last year is still signed       |
| The intended audience       | It may have been signed for a different service   |
| The recipient address       | It may be meant for another of altero's addresses |
| The request it answers      | It may answer a sign-in nobody here started       |
| That it was not used before | Nothing in SAML prevents presenting one twice     |

Three deliberate limits: sign-in must **start at altero**, because an unsolicited assertion answers no request and accepting one means accepting anything the key ever signed; **encrypted assertions are not supported**, since TLS already protects the connection; and there is **no single logout**, which is unreliable in practice, and altero's session is its own.

## Deliberate differences from zotero.org

### Deliberate differences

Six places where altero does not copy zotero.org:

- **No `alternate` links.** zotero.org links every object to its page on zotero.org. altero will not send clients to somebody else's copy of the data, and its own interface has no page per object, so envelopes carry only `self` and `up`. A single-page response therefore has no `Link` header — except group listings, which carry `self` because the desktop needs the header (see [Who the client finds in a group](#who-the-client-finds-in-a-group)).
- **An unknown `locale` falls back to `en-US`.** zotero.org answers 500.
- **Rate limiting is off unless configured.** A self-hosted server with a handful of clients rarely needs it; set `ALTERO_RATE_LIMIT` to turn it on.
- **Fields with the same translated name may be ordered differently.** Three fields are called "Format"; zotero.org orders them by an internal number the published schema lacks.
- **Tags can be renamed through the API** — see [Renaming a tag](#renaming-a-tag). An addition rather than a change: nothing that reads tags behaves differently.
- **altero makes requests of its own**, in one place only: [reading a library out of zotero.org](#reading-a-library-out-of-zoteroorg).
