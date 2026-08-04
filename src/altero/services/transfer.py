"""Moving a whole library out of one instance and into another.

The requirement that shapes all of this is exactness. A library is not a bag of
objects, it is a set of objects at particular versions, and clients remember
those versions: a restore that renumbers them looks like it worked and then
locks out every client that had synced against the original, in both directions
at once. So the archive carries versions -- the library's and every object's --
along with the timestamps the client supplied, the deletion log that lets a
client tell a removed object from one it never fetched, and the attachment bytes
without which every attachment points at nothing.

Accounts and credentials are deliberately not in it. An archive is a library,
not a user: it can be restored under a different account on a different server,
and it cannot leak an API key by being copied around.
"""

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero import __version__
from altero.errors import InvalidInputError, NotFoundError
from altero.models import (
    Collection,
    CollectionItem,
    CollectionRelation,
    DeletedObject,
    FullText,
    Item,
    ItemCreator,
    ItemField,
    ItemRelation,
    ItemTag,
    Library,
    LibraryType,
    SavedSearch,
    SearchCondition,
    Setting,
    Tag,
)
from altero.services import storage

#: Bumped when the archive layout changes in a way an older altero cannot read.
FORMAT_VERSION = 1

MANIFEST = "manifest.json"
FILE_PREFIX = "files/"


def _moment(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def _resolve(session: AsyncSession, library_type: LibraryType, owner_id: int) -> Library:
    library = await session.scalar(
        select(Library).where(Library.type == library_type, Library.owner_id == owner_id)
    )
    if library is None:
        raise NotFoundError(f"No {library_type.value} library with id {owner_id}")
    return library


async def export_library(
    session: AsyncSession,
    *,
    library_type: LibraryType,
    owner_id: int,
    storage_root: Path,
    destination: Path,
) -> Path:
    """Write the whole of one library to ``destination`` and return the path."""
    library = await _resolve(session, library_type, owner_id)

    items = list(
        await session.scalars(select(Item).where(Item.library_id == library.id).order_by(Item.id))
    )
    keys_by_id = {item.id: item.key for item in items}

    collections = list(
        await session.scalars(
            select(Collection).where(Collection.library_id == library.id).order_by(Collection.id)
        )
    )
    collection_keys = {collection.id: collection.key for collection in collections}

    searches = list(
        await session.scalars(
            select(SavedSearch).where(SavedSearch.library_id == library.id).order_by(SavedSearch.id)
        )
    )
    tags = list(
        await session.scalars(select(Tag).where(Tag.library_id == library.id).order_by(Tag.id))
    )
    tag_keys = {tag.id: tag.key for tag in tags}

    membership = [
        (collection_keys[row.collection_id], keys_by_id[row.item_id])
        for row in await session.scalars(
            select(CollectionItem).where(CollectionItem.collection_id.in_(collection_keys))
        )
    ]
    item_tags = [
        (tag_keys[row.tag_id], keys_by_id[row.item_id])
        for row in await session.scalars(select(ItemTag).where(ItemTag.tag_id.in_(tag_keys)))
    ]

    settings = list(await session.scalars(select(Setting).where(Setting.library_id == library.id)))
    fulltext = list(
        await session.scalars(select(FullText).where(FullText.library_id == library.id))
    )
    deletions = list(
        await session.scalars(select(DeletedObject).where(DeletedObject.library_id == library.id))
    )

    documents = {
        "items.json": [
            {
                "key": item.key,
                "version": item.version,
                "itemType": item.item_type,
                "parent": keys_by_id.get(item.parent_id) if item.parent_id else None,
                "deleted": item.deleted,
                "inPublications": item.in_publications,
                "sortTitle": item.sort_title,
                "sortCreator": item.sort_creator,
                "sortDate": item.sort_date,
                "dateAdded": _moment(item.date_added),
                "dateModified": _moment(item.date_modified),
                "serverDateModified": _moment(item.server_date_modified),
                "fields": [{"field": f.field, "value": f.value} for f in item.fields],
                "creators": [
                    {
                        "position": c.position,
                        "creatorType": c.creator_type,
                        "firstName": c.first_name,
                        "lastName": c.last_name,
                        "name": c.name,
                    }
                    for c in item.creators
                ],
                "relations": [
                    {"predicate": r.predicate, "object": r.object} for r in item.relations
                ],
            }
            for item in items
        ],
        "collections.json": [
            {
                "key": collection.key,
                "version": collection.version,
                "name": collection.name,
                "parent": collection_keys.get(collection.parent_id)
                if collection.parent_id
                else None,
                "deleted": collection.deleted,
                "dateAdded": _moment(collection.date_added),
                "dateModified": _moment(collection.date_modified),
                "serverDateModified": _moment(collection.server_date_modified),
                "items": sorted(item for name, item in membership if name == collection.key),
                "relations": [
                    {"predicate": r.predicate, "object": r.object} for r in collection.relations
                ],
            }
            for collection in collections
        ],
        "searches.json": [
            {
                "key": search.key,
                "version": search.version,
                "name": search.name,
                "deleted": search.deleted,
                "dateAdded": _moment(search.date_added),
                "dateModified": _moment(search.date_modified),
                "serverDateModified": _moment(search.server_date_modified),
                "conditions": [
                    {
                        "position": c.position,
                        "condition": c.condition,
                        "operator": c.operator,
                        "value": c.value,
                    }
                    for c in search.conditions
                ],
            }
            for search in searches
        ],
        "tags.json": [
            {
                "key": tag.key,
                "name": tag.name,
                "type": tag.type,
                "version": tag.version,
                "dateAdded": _moment(tag.date_added),
                "dateModified": _moment(tag.date_modified),
                "serverDateModified": _moment(tag.server_date_modified),
                "items": sorted(item for key, item in item_tags if key == tag.key),
            }
            for tag in tags
        ],
        "settings.json": [
            {"name": setting.name, "value": setting.value, "version": setting.version}
            for setting in settings
        ],
        "fulltext.json": [
            {
                "item": keys_by_id[text.item_id],
                "content": text.content,
                "version": text.version,
                "indexedChars": text.indexed_chars,
                "totalChars": text.total_chars,
                "indexedPages": text.indexed_pages,
                "totalPages": text.total_pages,
            }
            for text in fulltext
        ],
        "deleted.json": [
            {
                "objectType": record.object_type,
                "key": record.key,
                "version": record.version,
                "deleted": _moment(record.deleted),
            }
            for record in deletions
        ],
    }

    # Attachments are stored once per digest, so the archive carries them the
    # same way: two items sharing a file do not carry it twice.
    digests = sorted(
        {
            value
            for item in items
            for field, value in ((f.field, f.value) for f in item.fields)
            if field == "md5" and value
        }
    )
    present = [(digest, storage.file_path(storage_root, digest)) for digest in digests]
    present = [(digest, path) for digest, path in present if path.is_file()]

    manifest = {
        "format": FORMAT_VERSION,
        "altero": __version__,
        "library": {
            "type": library.type.value,
            "id": library.owner_id,
            "version": library.version,
        },
        "name": library.name,
        "counts": {
            "items": len(items),
            "collections": len(collections),
            "searches": len(searches),
            "tags": len(tags),
            "settings": len(settings),
            "fulltext": len(fulltext),
            "deleted": len(deletions),
            "files": len(present),
        },
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(MANIFEST, json.dumps(manifest, indent=2))
        for name, document in documents.items():
            bundle.writestr(name, json.dumps(document, indent=2))
        for digest, path in present:
            bundle.write(path, f"{FILE_PREFIX}{digest}")

    return destination


async def _is_empty(session: AsyncSession, library: Library) -> bool:
    for model in (Item, Collection, SavedSearch, Tag, Setting, DeletedObject):
        if await session.scalar(select(model).where(model.library_id == library.id).limit(1)):
            return False
    return True


async def clear_library(session: AsyncSession, library: Library) -> None:
    """Remove everything belonging to a library, link tables first.

    Public because deleting a group needs exactly this, plus the rows that only
    a group has -- see :func:`altero.services.groups.delete_group`.
    """
    items = select(Item.id).where(Item.library_id == library.id)
    collections = select(Collection.id).where(Collection.library_id == library.id)

    await session.execute(delete(ItemTag).where(ItemTag.item_id.in_(items)))
    await session.execute(
        delete(CollectionItem).where(CollectionItem.collection_id.in_(collections))
    )
    await session.execute(
        delete(CollectionRelation).where(CollectionRelation.collection_id.in_(collections))
    )
    await session.execute(delete(FullText).where(FullText.library_id == library.id))
    await session.execute(delete(ItemField).where(ItemField.item_id.in_(items)))
    await session.execute(delete(ItemCreator).where(ItemCreator.item_id.in_(items)))
    await session.execute(delete(ItemRelation).where(ItemRelation.item_id.in_(items)))
    # Children before parents, or the self-reference blocks the delete.
    await session.execute(
        delete(Item).where(Item.library_id == library.id, Item.parent_id.isnot(None))
    )
    await session.execute(delete(Item).where(Item.library_id == library.id))
    await session.execute(
        delete(SearchCondition).where(
            SearchCondition.search_id.in_(
                select(SavedSearch.id).where(SavedSearch.library_id == library.id)
            )
        )
    )
    await session.execute(delete(SavedSearch).where(SavedSearch.library_id == library.id))
    await session.execute(
        delete(Collection).where(
            Collection.library_id == library.id, Collection.parent_id.isnot(None)
        )
    )
    await session.execute(delete(Collection).where(Collection.library_id == library.id))
    await session.execute(delete(Tag).where(Tag.library_id == library.id))
    await session.execute(delete(Setting).where(Setting.library_id == library.id))
    await session.execute(delete(DeletedObject).where(DeletedObject.library_id == library.id))
    await session.flush()


async def import_library(
    session: AsyncSession,
    *,
    archive: Path,
    storage_root: Path,
    replace: bool = False,
) -> Library:
    """Restore an archive into the library it names, and return it."""
    if not archive.is_file():
        raise NotFoundError(f"No archive at {archive}")

    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read(MANIFEST))
        if manifest.get("format") != FORMAT_VERSION:
            raise InvalidInputError(
                f"Unsupported archive format {manifest.get('format')}; "
                f"this altero reads {FORMAT_VERSION}"
            )

        documents: dict[str, Any] = {
            name: json.loads(bundle.read(name))
            for name in (
                "items.json",
                "collections.json",
                "searches.json",
                "tags.json",
                "settings.json",
                "fulltext.json",
                "deleted.json",
            )
        }

        described = manifest["library"]
        library = await _resolve(session, LibraryType(described["type"]), described["id"])

        if not await _is_empty(session, library):
            if not replace:
                raise InvalidInputError(
                    f"Library {described['type']}/{described['id']} is not empty; "
                    "restoring would merge two libraries rather than replace one"
                )
            await clear_library(session, library)

        # Items first and parents second: a child cannot name a row that does
        # not exist yet, and the archive stores parents by key.
        item_ids: dict[str, int] = {}
        for record in documents["items.json"]:
            item = Item(
                library_id=library.id,
                key=record["key"],
                version=record["version"],
                item_type=record["itemType"],
                deleted=record["deleted"],
                # Older archives predate the flag, so absence means false.
                in_publications=record.get("inPublications", False),
                sort_title=record["sortTitle"],
                sort_creator=record["sortCreator"],
                sort_date=record["sortDate"],
                date_added=_parse(record["dateAdded"]),
                date_modified=_parse(record["dateModified"]),
                server_date_modified=_parse(record["serverDateModified"]),
            )
            item.fields = [ItemField(field=f["field"], value=f["value"]) for f in record["fields"]]
            item.creators = [
                ItemCreator(
                    position=c["position"],
                    creator_type=c["creatorType"],
                    first_name=c["firstName"],
                    last_name=c["lastName"],
                    name=c["name"],
                )
                for c in record["creators"]
            ]
            item.relations = [
                ItemRelation(predicate=r["predicate"], object=r["object"])
                for r in record["relations"]
            ]
            session.add(item)
            await session.flush()
            item_ids[item.key] = item.id

        for record in documents["items.json"]:
            if record["parent"]:
                child = await session.get(Item, item_ids[record["key"]])
                if child is not None:
                    child.parent_id = item_ids[record["parent"]]

        collection_ids: dict[str, int] = {}
        for record in documents["collections.json"]:
            collection = Collection(
                library_id=library.id,
                key=record["key"],
                version=record["version"],
                name=record["name"],
                deleted=record["deleted"],
                date_added=_parse(record["dateAdded"]),
                date_modified=_parse(record["dateModified"]),
                server_date_modified=_parse(record["serverDateModified"]),
            )
            # Older archives predate collection relations.
            collection.relations = [
                CollectionRelation(predicate=r["predicate"], object=r["object"])
                for r in record.get("relations", [])
            ]
            session.add(collection)
            await session.flush()
            collection_ids[collection.key] = collection.id

        for record in documents["collections.json"]:
            stored = await session.get(Collection, collection_ids[record["key"]])
            if stored is None:  # pragma: no cover - just inserted
                continue
            if record["parent"]:
                stored.parent_id = collection_ids[record["parent"]]
            for item_key in record["items"]:
                session.add(CollectionItem(collection_id=stored.id, item_id=item_ids[item_key]))

        for record in documents["searches.json"]:
            search = SavedSearch(
                library_id=library.id,
                key=record["key"],
                version=record["version"],
                name=record["name"],
                deleted=record["deleted"],
                date_added=_parse(record["dateAdded"]),
                date_modified=_parse(record["dateModified"]),
                server_date_modified=_parse(record["serverDateModified"]),
            )
            search.conditions = [
                SearchCondition(
                    position=c["position"],
                    condition=c["condition"],
                    operator=c["operator"],
                    value=c["value"],
                )
                for c in record["conditions"]
            ]
            session.add(search)

        for record in documents["tags.json"]:
            tag = Tag(
                library_id=library.id,
                key=record["key"],
                name=record["name"],
                type=record["type"],
                version=record["version"],
                date_added=_parse(record["dateAdded"]),
                date_modified=_parse(record["dateModified"]),
                server_date_modified=_parse(record["serverDateModified"]),
            )
            session.add(tag)
            await session.flush()
            for item_key in record["items"]:
                session.add(ItemTag(tag_id=tag.id, item_id=item_ids[item_key]))

        for record in documents["settings.json"]:
            session.add(
                Setting(
                    library_id=library.id,
                    name=record["name"],
                    value=record["value"],
                    version=record["version"],
                )
            )

        for record in documents["fulltext.json"]:
            session.add(
                FullText(
                    library_id=library.id,
                    item_id=item_ids[record["item"]],
                    content=record["content"],
                    version=record["version"],
                    indexed_chars=record["indexedChars"],
                    total_chars=record["totalChars"],
                    indexed_pages=record["indexedPages"],
                    total_pages=record["totalPages"],
                )
            )

        for record in documents["deleted.json"]:
            session.add(
                DeletedObject(
                    library_id=library.id,
                    object_type=record["objectType"],
                    key=record["key"],
                    version=record["version"],
                    deleted=_parse(record["deleted"]),
                )
            )

        # Last, and the point of the exercise: the version clients remember.
        library.version = described["version"]
        library.name = manifest.get("name", library.name)

        for entry in bundle.namelist():
            if not entry.startswith(FILE_PREFIX):
                continue
            digest = entry[len(FILE_PREFIX) :]
            path = storage.file_path(storage_root, digest)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bundle.read(entry))

    await session.commit()
    return library
