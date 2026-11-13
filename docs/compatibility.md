# Compatibility reference

Use this reference when integrating a client or investigating behavior that
differs from Zotero's published API documentation. Each decision describes the
observable result and its reason.

altero targets unmodified Zotero Desktop. Where documentation disagrees with
behavior clients depend on, compatibility wins. Evidence includes the live API,
the [reference dataserver](https://github.com/zotero/dataserver) and real-client
checks. Inferences and untested behavior are marked explicitly.

For setup and ordinary use, start with [Clients](clients.md) or the
[web guide](web-interface.md).

## API queries and response behavior

### Omitted note content in partial writes

A partial write that leaves out `note` keeps the existing note text, for notes and attachments alike. Sending `note: ""` clears it. A full replacement (`PUT`) still replaces everything. This matches the dataserver, which only touches the note when the property is present.

### Empty creators in item responses

Regular items include `creators: []` when empty. Omitting it from a sync
response makes an existing desktop retain its previous creators. Notes,
attachments and annotations have no creator list.

### Racing ZIP archives of different sizes

When the client uploads a web snapshot, `md5` describes the file inside the archive and `zipMD5` the archive itself. Two clients zipping the same snapshot produce archives of different sizes with the same `md5`.

Each archive is stored under its own `zipMD5`, as on zotero.org, so neither replaces the other: both registrations succeed, and each attachment downloads the archive its own client sent.

### Search syntax

The `itemType` and `tag` parameters behave differently from what the documentation suggests, in two ways that change results.

**Negation covers the whole value.** `itemType=-book || journalArticle` excludes *both* types; it does not mean "not a book, or a journal article". This was confirmed by counting against a real library of 442 items: `itemType=attachment || note` matched 134 and `itemType=-attachment || note` returned exactly 308.

**`||` only separates when there is whitespace on both sides.** `tag=a||b` is one tag literally named `a||b`, and so is `tag=a ||b`. This lets a tag containing `||` round-trip. Every documented example uses the spaced form, so clients are unaffected.

A leading hyphen is escaped as `\-`. Only the whole value is trimmed, once, so inner spacing in `tag=foo bar || bar` survives.

### Quick search and full-text search

Quick search combines words with AND across the title, note title, creators
and year. Double quotes group a phrase; single quotes do not. As upstream,
unquoted `q=0` applies no filter, while `q="0"` searches for zero.

With `qmode=everything`, altero also searches stored attachment text and every
item field. It uses database substring matching instead of a separate search
service. The differences are:

- Character substrings match: `equod` finds *Pequod*. Punctuation can interrupt a phrase match.
- Accents are significant; case is ignored across alphabets. Chinese and Japanese terms require consecutive characters.
- `%` and `_` act as wildcards. Terms shorter than three characters require a slower scan.
- All fields are searched, including fields upstream omits.
- There is no upstream-style 300-hit full-text cap.

Upstream's documented analyzer defaults imply different word and phrase behavior;
that analyzer comparison is an inference, not a direct measurement.

`/top` returns the parent of a matching child for `q`, `tag`, `itemKey` and
`itemType`. All words must match the same item. `since` does not promote a
child to its parent. Neither a trashed match nor a trashed parent is returned.

Tag-name search is case-sensitive: `/tags?q=fic` does not find *Fiction*.
It also accepts `%` and `_` wildcards, escaped with a backslash when literal.

### Tag counts and the trash

Library-wide `/tags` counts include trashed items, even with
`includeTrashed=0`. A tag carried only by trashed items remains listed. This
matches reviewed upstream behavior ([dataserver#51](https://github.com/zotero/dataserver/issues/51));
it is source evidence, not a new live measurement.

Use `/items/tags` for live-item counts or `/items/trash/tags` for Trash.
`includeTrashed=1` widens the former. Collection scopes and restricted OAuth
grants still limit which items are counted. The browser uses item-scoped counts.

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

The published schema gives attachments only `title`, `accessDate` and `url`, and notes and annotations no fields at all. In reality an attachment also has `linkMode`, `contentType`, `charset`, `filename`, `md5`, `mtime` and `path`; a note has `note`; and an annotation has the `annotation*` fields. Validating strictly against the published schema would even reject the server's own `/items/new` template, so altero accepts these fields too. Any other field outside the schema is still refused, so a storage field on a book is an error. `md5` must be a 32-character digest, as zotero.org requires: the server serves the file a stored digest names, so a value that is not a digest is refused rather than allowed to name a file outside the store.

If a write is refused with `Invalid field`, this is the first thing to check.

**`md5` and `mtime` are `null` until a file has been uploaded**, on attachments that store a file. A write that sends either as empty does not overwrite a stored value. The Android app depends on this: an empty string instead of `null` stopped it from ever uploading the file.

### Timestamps

`dateAdded` and `dateModified` come from the client and are stored unchanged, so uploading an existing library keeps its history. `serverDateModified` is always the server's own time, so no client can reorder results by changing its own clock.

### Citations and bibliographies

Citation rendering runs locally with packaged CSL styles. No network fetch is
needed during a request. CSL field mapping follows Zotero's schema.

| Request | Behavior |
| --- | --- |
| `format=csljson` | Wraps entries in `{"items": [...]}`, including a single item |
| `format=bib` | One document, at most 150 items; `Total-Results` but no pagination links |
| `format=bib` with sorting or paging parameters | 400 |
| `include` outside JSON, an unknown include, or `none` combined with another | 400 |
| Unknown style name | 404; renamed styles retain their aliases |
| Style supplied as a URL | 400; arbitrary remote styles are not fetched |

`include` accepts `data`, `bib`, `citation`, `csljson`, `none` and supported
export formats. Atom uses `content` for HTML. Titles and names escape markup
except supported rich-text formatting such as italics, bold, superscript,
subscript, small caps and `nocase`.

The server provides Zotero's bibliography export formats. API exports omit
attachment bytes and child-note bundles; individual notes or attachments are
handled as each format permits. BibTeX, BibLaTeX and RIS use CSL data, so some
types become `@misc` or `GEN`. Citation keys use author, year and title with
collision suffixes; an explicit `citationKey` takes precedence.

Deliberate output differences:

- EndNote XML and Evernote identify altero as the writer.
- XML and RDF preserve content without matching upstream whitespace.
- CSV's Date Added contains the added date rather than the modified date.
- Bookmarks and Evernote escape special characters correctly; Evernote dates have one trailing `Z`, and missing URLs are empty.
- Multiple ISBNs do not create an extra empty RDF entry.
- Duplicate TEI IDs receive suffixes as they are streamed.

Formatted citations preserve hanging indents and line spacing but do not
reproduce numbered-style `second-field-align`. APA may repeat a title when an
item lacks an author, a [known processor limitation](https://github.com/citeproc-py/citeproc-py/issues/91).

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

Registration therefore checks the stored file against its digest before attaching it. A file that is not what was sent is removed and the registration refused; the client treats that as a file-sync error and sends the file again on its next sync. Every stored file is named by the digest of its own bytes, so a mismatch is always damage.

**An attachment can claim a file the server does not have.** A library moved from zotero.org whose files were kept on WebDAV names a digest for every attachment, but none of the files. So `If-None-Match: *` ("is there a file to protect?") is answered by looking for the file itself, not at what the attachment claims; otherwise the upload that would repair the attachment is refused. `If-Match` is still checked against the attachment, because that is how the client proves it is not working from stale information.

**A download serves the file an upload registered, not the one the attachment claims**, as on zotero.org. `md5` is metadata any client may write, and files are shared by digest across libraries, so serving the claim would hand anybody who knew a digest the file behind it. Writing `md5` therefore changes what the attachment says and not which bytes it serves; an attachment no upload gave a file answers 404. A library copied from another, restored from an archive that carries the file, or upgraded from an earlier altero keeps the file it had.

**`{"exists": 1}` needs the digest and the exact size**, as on zotero.org: that answer gives the client the stored file without receiving a byte. The digest is the archive's, `zipMD5`, for a snapshot. Where the size differs, zotero.org refuses with 400; altero asks for the bytes instead, which then prove themselves, so a stored file that was damaged can be repaired by the next client that holds it.

**No upload or restore can replace another library's file.** A snapshot's `md5` names the file inside the archive, and an archive's `files/` entry names whatever its maker wrote there; neither is checked against the bytes. So the bytes are stored under their own digest, never under a name somebody gave them.

#### Downloading is a redirect, and has to be

Asking for an attachment's file answers **302**, with three headers:

| Header                          | What it says                                             |
|---------------------------------|----------------------------------------------------------|
| `Zotero-File-Modification-Time` | the modification time the uploading client declared      |
| `Zotero-File-MD5`               | the attachment's file: for a snapshot, the one inside    |
| `Zotero-File-Compressed`        | `Yes` when the stored bytes are a ZIP around that file   |

The desktop reads these headers from the redirect and nowhere else. Answering 200 with the bytes makes every download fail with "A file sync error occurred". The redirect also lets the client skip the download entirely when the modification time shows its copy is current.

##### The location has to be a credential

The desktop makes a new request to the redirect location without its API key.
altero therefore issues a full URL at `/storage/download/<key>` that grants
access to just that file for five minutes. It permits retries and forbids
shared caching.

The URL never contains the account's long-lived API key. Callers that already
hold a key can also fetch bytes directly at `<prefix>/items/<key>/file/content`.

#### Telling an archive from a file

The desktop zips a web snapshot before uploading it. If a download then says `Zotero-File-Compressed: No`, the client saves the ZIP itself under the attachment's name, and the snapshot is quietly lost.

altero records which is which when the file is registered: an upload that came with a `zipMD5` is an archive around the attachment's file, and a `.docx` or `.epub` — a ZIP itself — uploaded without one is served as it is. An archive restored into a library is one when its own digest is not the name the archive filed it under and it starts like a ZIP, which is how earlier altero versions stored snapshots.

## Authentication and client login

### Obtaining a key

The desktop creates a login session with `POST /keys/sessions`, opens its
`loginURL`, and polls until approved. A completed response includes `apiKey`,
`userID`, `username`, `displayName` and `emails`.

Approval in altero requires fresh identity confirmation before issuing a
long-lived key. The key includes group access so the client does not mistake
unreadable groups for lost libraries. Shell approval remains available when
the browser interface is not built.

A profile requesting one account number cannot be approved for another: the
client would offer to reset its data directory. Changing the username alone
is safe because the client identifies the account by number.

Usernames cannot contain `@`; sign-in distinguishes usernames from email
addresses by that character. An account has at most one email address and
reports it only after confirmation. `loginURL` always has a query so mobile
clients can append `&app=1`.

Legacy password-to-key `POST /keys` is unsupported. Key management is available
in Settings and the CLI, rather than through `/users/<id>/keys`. A key may
read `/keys/current` and revoke itself.

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

The desktop relies on behavior beyond the published request examples:

- `mtime` is a numeric millisecond timestamp and requires 64-bit storage.
- Full text is uploaded as a `POST <prefix>/fulltext` batch with `If-Unmodified-Since-Version`. Result entries are objects containing `key`.
- Recreating a setting clears its deletion record, so deletion processing does not erase the new value.
- A bare `DELETE <prefix>/tags` answers 204 without deleting anything. The client can drop the query naming the tags; it accepts only 204 or 412. An explicit `tags=a||b` is also supported.
- Gzipped bodies are accepted. Compressed and expanded bodies are each limited to 128 MiB; invalid compression returns 400 and excess size returns 413.
- Snapshots carry `md5` for the main file and `zipMD5` for the archive. Transfer validation uses the archive digest.
- Upload addresses must be absolute URLs.
- Batch uploads contain partial changes after the first sync; see [patch semantics](#a-posted-batch-is-a-batch-of-patches).
- File registration advances the library version. A following stale full-text upload can receive 412 and retry after syncing.

A client's version ahead of the server is accepted, as upstream. The desktop
then refuses a lower response version. Raising the server counter resolves
that mismatch but recreates no data; follow the
[recovery procedure](administration.md#after-recreating-the-database).

Retraction-list requests return 404 because altero has no retraction data.
The client logs the error and continues syncing.

The streaming URL is independent of the API URL. Configure both, or disable
streaming explicitly, to avoid sending the altero key to Zotero's default
streaming service. See [client setup](clients.md).

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

An obsolete upstream publications guard returned 400 for some libraries. altero does not reproduce that legacy refusal, which would break current clients.

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
- **The license chooser remains available afterwards.** The desktop never shows its wizard twice for an item; a different license is typed into the **Rights** field. The browser offers a chooser with the same licenses and free text. It refuses the edit if **Rights** changed in the meantime; changes to other fields do not prevent saving.
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

Regular-item sync responses include empty `creators`, `tags`, `collections` and `relations`; see [Empty creators](#empty-creators-in-item-responses).

**Changing an item's type keeps what the new type can hold.** A field the new type lacks moves to its equivalent there, as a book's `publisher` becomes a report's `institution`, or is cleared. A creator whose role the new type lacks becomes a `contributor`. A field sent empty is accepted even if the new type lacks it, because that is how the desktop clears one: it uploads `{key, version, itemType}` with every field the item lost set to `""`. Fields and creators sent with the type are taken as sent.

**`parentItem: false` makes a child top-level.** The desktop sends it when a note or attachment is moved out to the library. As on zotero.org, a patch that files a child in a collection without mentioning `parentItem` does the same, since a child cannot be in a collection.

### Objects that were sent again without changing

An object identical to the stored one is reported as `unchanged` and keeps its version, as on zotero.org. Saving it again would advance the library version and make every other client download an object that never changed.

Everything a client can set counts as a change: type, fields, creators and their order, relations, parent, trash flag, `dateAdded`, `dateModified`, tags and collections. The server's own values — the version and `serverDateModified` — do not. Leaving `dateModified` out is no change by itself: the server stamps it only when something else changed. A batch in which nothing changed leaves the library version as it was.

Settings follow the same rule: a setting is changed only if its value differs, so `3` and `3.0` differ but `3` and `3` do not. A request that changes no setting answers 204 with the library version unchanged; in a batch, only the settings that changed get the new version.

The current dataserver advances the library version for each object in a batch, even an unchanged one. altero advances it once per request that changes something. Object versions and the reported results still agree; only the library's version number can differ between the two servers.

Two places skip this check, as on zotero.org: a single-object `PUT` or `PATCH`, which has no report to put the answer in, and the full-text batch.

### An object that depends on one the server lacks

An item naming a parent item or a collection that does not exist, or a collection naming a parent collection that does not exist, fails with 409, as on zotero.org. In a batch, the failure names the missing object in `data`:

| Missing           | `message`                       | `data`                |
|-------------------|---------------------------------|-----------------------|
| Parent item       | `Parent item K not found`       | `{"parentItem": "K"}` |
| Collection        | `Collection K not found`        | `{"collection": "K"}` |
| Parent collection | `Parent collection K not found` | `{"collection": "K"}` |

The desktop reads `data` to repair its own state: if it holds the missing object but has not queued it, it marks it for upload and syncs again. Without `data`, the same item fails on every sync.

An object outside what the credential may read is reported as missing in the same way, so a write cannot be used to learn whether a key exists.

### What may be a child of what

The rules are zotero.org's, and the desktop applies the same ones before it uploads:

| Item          | May hang off                                                                 |
|---------------|------------------------------------------------------------------------------|
| Regular item  | nothing                                                                      |
| Note          | a regular item                                                               |
| Attachment    | a regular item; an embedded image (a picture in a note) also a note          |
| Annotation    | a file attachment, required: a highlight, underline or note annotation on a PDF, EPUB or HTML snapshot; an image, ink or text annotation on a PDF |

A note or attachment under a note or attachment fails with 409, `Parent item cannot be a note or attachment`, naming the parent in `data`. The other refusals fail with 400, including an item named as its own parent.

The rules are checked when an item is created or moved to another parent. An item already stored under a parent it could not have now, for example by an earlier altero, keeps syncing as it is.

**Child items cannot belong to collections.** Making a standalone note or attachment a child removes its former collection memberships, even when the upload omits `collections`. Explicitly assigning a child to a collection fails with 400, as on zotero.org.

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

#### Group renames notify connected clients

A group rename advances its advertised version and sends a committed
`topicUpdated` event, so clients refresh their cached group name. Item versions
need not change. Upstream's missing-notification report is unverified against
the hosted service; altero deliberately keeps this behavior
([dataserver#92](https://github.com/zotero/dataserver/issues/92)).

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

The browser uses the same operation; see [Tags](web/library.md#tags).

### The desktop client's three extra views

These views exist only in the browser. Zotero computes them from its local
library; its API has no corresponding scopes.

| View | altero behavior |
| --- | --- |
| Unfiled Items | Untrashed top-level items in no collection |
| Duplicate Items | Shared normalized DOI/ISBN, or normalized title plus matching surname or year; title alone only when neither has creators or year |
| Recently Read | Items with attachments read within 90 days, and standalone attachments read in that period |

Duplicate detection compares regular items across types. It suggests candidates,
not proof that they are the same work. The 90-day reading window is an explicit
guess; the desktop's exact rule is undocumented.

There is no v3 `/items/unfiled`. Unknown query parameters are ignored, so
`scope=unfiled` or `unfiled=1` on a v3 item listing does not filter it.

### Merging PDFs with embedded notes

When deduplication would both move a surviving PDF to the master and transfer
another PDF's embedded note to it, altero keeps both PDFs under the master.
Each keeps its original note and annotations. Other PDF matching follows the
desktop's byte and common-word checks.

A recorded desktop defect can save the note while losing the parent change. Keeping both files avoids leaving the survivor under a trashed duplicate. See the [historical desktop evidence](client-compatibility.md#successfully-tested-matrix).

### Reading a library out of zotero.org

The migration reads a personal library from api.zotero.org and turns it into the same archive `altero library export` writes, then restores that archive. It makes no writes to zotero.org.

Attachment downloads may redirect to another origin. Those requests carry no
API key, including any subsequent redirects back to the API.

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

### Continuous sync with zotero.org

**Continuous two-way sync is unsupported and is not feasible as a transparent
mode for unmodified Zotero Desktop.** Each server assigns library and object
versions independently. After a migration, version 100 on altero and version
100 on zotero.org can describe different changes. The desktop remembers one
server's watermark and cached object versions; changing the API address does
not reconcile those histories. Keeping the same account number and item keys
does not solve that problem.

A separate replication service would need its own per-server version history,
conflict resolution, deletion tracking, relation mapping and attachment
transfer. Copying objects and their version numbers back and forth is not such
a service. altero does not provide one, and alternating a desktop between
servers is not a supported way to keep them synchronized.

**A periodic one-way refresh from zotero.org into altero is feasible as future
work**, with zotero.org authoritative and the destination treated as a copy.
It would need to apply upstream changes and deletions through altero's own
versioned writes so already-connected clients can observe them. Local edits
would need an explicit refusal or overwrite policy. This is a design
assessment, not an implemented or tested refresh feature; scheduling and its
implementation remain future work.

Today, the CLI and browser offer a one-time personal-library import. Repeating
it with `--replace` restores a whole snapshot and can discard altero-only
changes. It does not perform incremental reconciliation, and raising the
library watermark alone cannot replace newer objects already cached by a
desktop with older imported versions. See [the exercised recovery limits](client-compatibility.md#additional-desktop-scenarios).
Use the [migration procedure](administration.md#move-a-personal-library-from-zoteroorg)
to move to altero, then keep that library's clients pointed at altero.

## The authorization server

### Token revocation

`/oauth/revoke` accepts the same client authentication methods as `/oauth/token`:
HTTP Basic, a form secret, or a public client's ID without a secret.
Confidential clients must authenticate, as [RFC 7009 §2.1](https://www.rfc-editor.org/rfc/rfc7009.html#section-2.1)
requires. An authenticated request gets 200 for an unknown token too, and cannot
revoke another client's token. Revoking an access token leaves its refresh token
usable; revoking a refresh token invalidates its whole family.

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

As a client, altero accepts an ID token delivered directly by a trusted
provider over TLS under the conditions [below](#not-verifying-the-id-tokens-signature).
As a provider, it signs its own ID tokens with RS256 and verifies its own
signatures during logout, using only its stored keys and fixed algorithm.

### No dynamic client registration

Applications must be registered by an operator. Redirect addresses and allowed
scopes are reviewed at registration; no dynamic registration endpoint is provided.

### PKCE is required, and `S256` is the only method

The `plain` method makes the challenge identical to the secret it protects, so anyone who intercepts the code has everything needed to use it. altero neither offers nor accepts it, and requires PKCE from every application, including those with a client secret.

### Scopes are refused rather than narrowed

An unknown scope, a scope the application is not registered for, or one useless without another is an error, rather than being quietly dropped. Dropping it would produce an application that half works and a person who cannot tell which half. `library.write` without `library.read` is the useless case.

There is no `annotations.*` scope: annotations are items, and the API has no separate permission for them.

## Identity-provider security notes

### Not verifying the ID token's signature

altero does not verify signatures on ID tokens received from an external
provider. OpenID Connect Core §3.1.3.7 item 6 permits reliance on TLS for a token
received directly from the token endpoint in this flow.

This requires altero to be a confidential client using authorization code and
PKCE, and to receive the token from the provider rather than the browser.
Issuer, audience, authorized party, nonce, expiry, issue time and subject are
still validated. Supporting public clients would require revisiting this choice.

### Reading a SAML assertion out of what was signed

Only claims inside the verified signed portion of a SAML document are read.
Signature verification is delegated to the XML-signature library. Altero also
checks success status, validity, audience, recipient, request correlation and
single use; a signature alone does not establish these.

Supported sign-in starts at altero and uses signed, unencrypted assertions.
Unsolicited assertions, encryption and SAML Single Logout are unsupported.

### Finishing SAML account linking with the browser session

A cross-site assertion POST lacks the existing browser session cookie. For
account linking and identity confirmation, altero verifies the assertion then
redirects through a short-lived GET handoff that can recover that session.

The same signed-in account must finish it within two minutes. Handles are
single-use, stored in the database for worker independence, and grant no access
without the matching session. Ordinary sign-in can create its session directly.
No browser cookie acquires Zotero API access.

## Deliberate differences from zotero.org

### Deliberate differences

Seven places where altero does not copy zotero.org:

- **No `alternate` links.** zotero.org links every object to its page on zotero.org. altero will not send clients to somebody else's copy of the data, and its own interface has no page per object, so envelopes carry only `self` and `up`. A single-page response therefore has no `Link` header — except group listings, which carry `self` because the desktop needs the header (see [Who the client finds in a group](#who-the-client-finds-in-a-group)).
- **An unknown `locale` falls back to `en-US`.** zotero.org answers 500.
- **A regular item given a parent fails with 400.** zotero.org answers 500 for the same refusal.
- **Rate limiting is off unless configured.** A self-hosted server with a handful of clients rarely needs it; set `ALTERO_RATE_LIMIT` to turn it on.
- **Fields with the same translated name may be ordered differently.** Three fields are called "Format"; zotero.org orders them by an internal number the published schema lacks.
- **Tags can be renamed through the API** — see [Renaming a tag](#renaming-a-tag). An addition rather than a change: nothing that reads tags behaves differently.
- **Library migration reads zotero.org** without writing back — see [import and continuous-sync limits](#continuous-sync-with-zoteroorg).
