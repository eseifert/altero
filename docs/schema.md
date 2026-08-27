# Database schema

This reference explains the data-model decisions that matter for Zotero compatibility. It compares altero with the official dataserver and focuses on substantive differences rather than naming conventions.

## Adopted from the dataserver

**Tag type belongs to the tag.** `tags` is unique on
`(libraryID, name, type)`, so a name added by hand and the same name added by a
translator are two rows rather than one tag with two links. altero originally
put `type` on the item/tag link, which would have merged them and reported one
type for both. Tags also carry an eight-character `key`, like every other
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

**Relations are stored per item.** The dataserver has a library-scoped
`relations(subject, predicate, object)` table plus `itemRelated` for
`dc:relation`. altero stores `(item, predicate, object)`, which produces the same
`relations` map in JSON but cannot express a relation whose subject is not an
item in the library.

**Sort keys are columns on the item.** The dataserver keeps `itemSortFields`
(`sortTitle` truncated to 79 characters, plus `creatorSummary`) in a side table
and joins `itemData` for date sorting. altero keeps `sort_title`, `sort_creator`
and `sort_date` on `items`, untruncated, so every sort is a single-table index
scan.

**No sharding.** `shards`, `shardHosts` and `shardLibraries` have no
counterpart: the dataserver spreads libraries across MySQL servers, and altero
uses one database.

**Files are stored by digest, not tracked per library.** The dataserver has
`storageFiles`, `storageFileItems`, `storageFileLibraries` and an upload queue,
because it hands uploads to S3 and has to account for them. altero writes the
bytes itself, under `<storage>/<first two characters of the digest>/<digest>`,
so identical files are stored once and the only table needed is
`storage_uploads` — one row per authorization, deleted once the upload is
registered. Nothing counts how many items reference a given file, so removing an
item leaves its bytes on disk; a collector that deletes unreferenced files is
not written yet.

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

`settings` matches the dataserver's, except that the value is stored as JSON
text: the server never interprets a setting, so there is nothing to model.

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

Without that lock, ten simultaneous creates were measured all receiving version
1, and nine of the ten items were lost — the surviving write overwrote the rest.
`tests/test_concurrency.py` reproduces this against PostgreSQL.

Two further get-or-create patterns — claiming a write token, and creating a tag
named by more than one concurrent request — insert first and let the unique
constraint decide, rather than looking and then inserting. With the library lock
held these cannot interleave, so the behavior is defense in depth: it keeps
them correct independently of the locking strategy above.

SQLite is configured with `foreign_keys=ON`, WAL and a busy timeout.
`BEGIN IMMEDIATE` is deliberately not used: it would close the remaining
lock-upgrade hole, but takes the write lock for read-only transactions too, so a
single long read would block every writer. A deployment serving several clients
at once should use PostgreSQL.
