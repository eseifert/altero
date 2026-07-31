# Database schema

altero's schema is compared against the official
[dataserver](https://github.com/zotero/dataserver), whose definitions live in
`misc/master.sql` (shared data) and `misc/shard.sql` (per-library data). The
dataserver shards libraries across MySQL servers; altero uses one database, so
the split between the two files is not reproduced.

Names differ throughout: the dataserver uses `camelCase` columns and singular
key names (`itemID`, `collectionName`), altero uses `snake_case` and plural
table names. Only differences of substance are listed below.

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
`itemAttachments`. altero stores a note's content as an ordinary field row. This
will need revisiting when the file protocol is implemented, since
`itemAttachments` carries the storage columns.

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

**No sharding, full-text or storage tables.** `shards`, `shardHosts`,
`itemFulltext`, `storageFiles` and the rest have no counterpart, because the
corresponding features are not implemented.

**The item type schema is not in the database.** The dataserver stores item
types, fields and their mappings in `master.sql` tables (`itemTypes`, `fields`,
`baseFieldMappings`, …). altero reads them from the vendored `schema.json`
instead, which keeps them in step with the published schema and out of
migrations. Item types and field names are therefore stored as strings rather
than as foreign keys to an ID table.

## Delete log

`syncDeleteLogKeys(libraryID, objectType, key, timestamp, version)` backs
`/deleted?since=`, with `objectType` one of `collection`, `creator`, `item`,
`relation`, `search`, `setting`, `tag` or `tagName`. Its primary key is
`(libraryID, objectType, key)`, so deleting a key that was deleted before
updates the existing row rather than adding a second one. altero mirrors this
shape in `deleted_objects`.
