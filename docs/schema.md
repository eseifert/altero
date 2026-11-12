# Database schema

For contributors changing persistence or synchronization. This reference lists
storage choices that affect API behavior. For migration commands, see the
[development guide](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#changing-the-database).

## Adopted from the dataserver

**Tag type belongs to the tag.** `tags` is unique on
`(libraryID, name, type)`, so a name added by hand and the same name added by a
translator are two rows rather than one tag with two links. Tags also carry an eight-character `key`, like every other
syncable object.

**Three timestamps per object.** `dateAdded` and `dateModified` are supplied by
the client and round-trip through the API; `serverDateModified` is set by the
server on every write. Keeping them apart is what makes the `serverDateModified`
sort trustworthy — a client cannot reorder another client's results by
backdating its own `dateModified`. Applied to items, collections, saved searches
and tags via the `Timestamped` mixin in `altero/db.py`.

**Versions start at 1**, not 0, matching `DEFAULT '1'` on every versioned table.

**Collections and searches are trashable.** The dataserver has
`deletedCollections` and `deletedSearches` alongside `deletedItems`, so the
trash is not an item-only concept.

## Deliberate differences

**Pending registration requests are separate from accounts.** The
`registration_requests` table is persistence for the planned verified-email and
administrator-approval workflow. It stores no password or usable credential and
creates no user or library. That public workflow is not enabled yet.

Pending rows reserve a canonical username and email address through unique,
nullable columns. Terminal rows release both reservations while retaining the
request's original fields. Constraints require email proof before review,
decision actor/time for approval or rejection, and an account ID for approval.
Actor and account IDs are historical values without foreign keys, so deleting
an account does not erase the recorded decision. They grant no access.

Internal submission defaults to disabled. When explicitly enabled by a trusted
caller, it normalizes the requested name/address, checks existing accounts and
reserves both values atomically. Requests expire at their deadline, releasing
both reservations while keeping history. Activation must recheck availability;
a pending reservation cannot override an account provisioned by an operator.

Verification recording accepts only a live email-pending request and the exact
normalized address its trusted mailbox-proof consumer verified. A replay cannot
refresh the proof or extend the deadline. After the caller authenticates the
applicant, cancellation releases either pending state; terminal history cannot
be reopened. Conditional updates resolve concurrent transitions. Cleanup shares
their transaction so a failed transition does not commit only part of the
operation. These are internal
primitives; applicant sessions and public routes remain to be wired.

An email-pending request can store one outstanding mailbox proof: a unique
SHA-256 token digest, the recipient address and an expiry no later than the
request deadline. The raw link token is never stored. All three proof fields
are present together or absent together; later states cannot retain them. This
internal issuer returns the stored recipient and a fresh random token, retaining
only its SHA-256 digest. Resending replaces the old proof without extending the
request deadline. A link lasts at most 24 hours; equality with either expiry
deadline is already too late.

Proof consumption checks the digest, saved recipient against the current address,
request state and both deadlines in one conditional update. The same update
clears the proof and moves the request to review; concurrent consumers have one
winner. Cancellation, expiry and trusted verification recording also clear any
outstanding token. A failed transaction preserves the earlier link and lifecycle
state together. These helpers send no mail and grant no account or library access;
mail policy, resend limits and applicant authorization still need caller integration.

**The trash is a flag, not a table.** The dataserver records trashed objects in
`deletedItems(itemID, dateDeleted)`; altero uses a `deleted` boolean on the
object. The queries are equivalent and the flag avoids a join on every listing.
The cost is that the deletion time is not kept, which nothing in the v3 API
exposes.

**Creators are not deduplicated.** The dataserver interns creators in a
`creators` table and links them through `itemCreators`, so one person shared by a
thousand items is stored once. altero stores creators inline on the item. This
trades space for simplicity; deduplication can be introduced behind the same
service functions if it ever matters.

**Notes and attachments are not separate tables.** The dataserver keeps
`itemNotes` (with a sanitized copy and an 80-character derived title) and
`itemAttachments`. altero stores both a note's content and an attachment's
storage columns as ordinary field rows in `item_fields`. Those fields are not in
the published schema, so the set each type accepts is declared in
`UNLISTED_FIELDS` in `services/itemwrites.py` rather than derived.

The upside is that one code path stores every field of every item type. The
cost is that nothing at the database level constrains an attachment to have a
`linkMode`, where a dedicated table would.

**Relations belong to objects.** Items and collections each have relation rows
that produce their API `relations` maps. This differs from upstream's general
library-scoped relation table.

**Sort keys are columns on the item.** The dataserver keeps `itemSortFields`
(`sortTitle` truncated to 79 characters, plus `creatorSummary`) in a side table
and joins `itemData` for date sorting. altero keeps `sort_title`, `sort_creator`
and `sort_date` on `items`, untruncated, so every sort is a single-table index
scan.

**No sharding.** `shards`, `shardHosts` and `shardLibraries` have no
counterpart: the dataserver spreads libraries across MySQL servers, and altero
uses one database.

**Files are stored by digest.** Identical registered bytes are stored once at
`<storage>/<first two digest characters>/<digest>`. Upload authorizations live
in `storage_uploads` until registration. Each attachment records its registered
file separately from client-supplied metadata, so a claimed digest does not
confer access to another library's bytes.

Deleting an item does not immediately remove its stored bytes. Administrators
can remove unreferenced and abandoned staging files from Storage, with a grace
period protecting uploads in progress.

**The item type schema is not in the database.** The dataserver stores item
types, fields and their mappings in `master.sql` tables (`itemTypes`, `fields`,
`baseFieldMappings`, …). altero reads them from the vendored `schema.json`
instead, which keeps them in step with the published schema and out of
migrations. Item types and field names are therefore stored as strings rather
than as foreign keys to an ID table.

## Tables with no direct counterpart

`write_tokens` records a `Zotero-Write-Token` for as long as a client might
retry with it, so a repeated request does not create the objects twice. The
dataserver caches these outside the database.

`item_fulltext` holds the text a client extracted from an attachment, matching
the dataserver's table of the same purpose, without the reindexing bookkeeping
that a hosted service needs.

`settings` stores sync setting values as JSON text rather than separate modeled fields.

## Delete log

`syncDeleteLogKeys(libraryID, objectType, key, timestamp, version)` backs
`/deleted?since=`, with `objectType` one of `collection`, `creator`, `item`,
`relation`, `search`, `setting`, `tag` or `tagName`. Its primary key is
`(libraryID, objectType, key)`, so deleting a key that was deleted before
updates the existing row rather than adding a second one. altero mirrors this
shape in `deleted_objects`.

## Concurrency

Writes to one library are serialized by taking a row lock on it before the
version precondition is checked and holding it until commit, so a request is
atomic with respect to its library. `SELECT ... FOR UPDATE` is emitted on
PostgreSQL and dropped on SQLite, which has a single writer anyway. The version
increment itself is computed by the database rather than in Python, so it stays
correct even without the lock.

Write-token and tag get-or-create operations use unique constraints rather
than a separate existence check followed by insertion. This preserves their
correctness independently of library locking.

SQLite is configured with `foreign_keys=ON`, WAL and a busy timeout.
`BEGIN IMMEDIATE` is deliberately not used: it would close the remaining
lock-upgrade hole, but takes the write lock for read-only transactions too, so a
single long read would block every writer. A deployment serving several clients
at once should use PostgreSQL.
