"""Creating, updating and deleting items."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.itemschema import get_schema
from altero.keys import coerce_key, is_valid_key
from altero.models import (
    Collection,
    CollectionItem,
    DeletedObjectType,
    Item,
    ItemCreator,
    ItemField,
    ItemRelation,
    ItemTag,
    Library,
    LibraryType,
    Tag,
    TagType,
)
from altero.services import itemdata
from altero.services.deletions import record_deletion
from altero.services.items import get_item
from altero.services.objectwrites import parse_relations, resolve_tag
from altero.services.writes import check_object_version

#: Keys of the item JSON that are not field values.
STRUCTURAL_KEYS = frozenset(
    {
        "key",
        "version",
        "itemType",
        "parentItem",
        "creators",
        "tags",
        "collections",
        "relations",
        "dateAdded",
        "dateModified",
        "deleted",
        "inPublications",
        # `note` is not in the schema's field list for any type, so it is
        # handled on its own below rather than as an ordinary field.
        "note",
    }
)

#: Item types whose JSON carries a `note` property.
NOTE_BEARING_TYPES = frozenset({"note", "attachment"})

#: Fields an item type accepts that the published schema does not list.
#:
#: The schema gives `attachment` only title, accessDate and url, and `note` and
#: `annotation` nothing at all, yet all three carry more than that in practice.
#: The attachment set was read off live responses and off the server's own
#: `/items/new` templates; the annotation set comes from the client's data model,
#: since the published schema names none of it.
UNLISTED_FIELDS: dict[str, frozenset[str]] = {
    "attachment": frozenset(
        {
            "linkMode",
            "contentType",
            "charset",
            "filename",
            "md5",
            "mtime",
            "path",
            # Added at schema version 42; the client uploads it on its own when
            # a snapshot is opened.
            "lastRead",
        }
    ),
    "annotation": frozenset(
        {
            "annotationType",
            "annotationAuthorName",
            "annotationText",
            "annotationComment",
            "annotationColor",
            "annotationPageLabel",
            "annotationSortIndex",
            "annotationPosition",
        }
    ),
}


def _parse_timestamp(value: Any, name: str) -> datetime | None:
    """Return a client-supplied timestamp, or ``None`` if it was not given.

    Clients round-trip their own ``dateAdded`` and ``dateModified``; dropping
    them would rewrite a library's history to the moment it was uploaded.
    """
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise InvalidInputError(f"Invalid '{name}' value '{value}'") from None


def _validate_creators(item_type: str, creators: Any) -> list[dict[str, str]]:
    """Check the ``creators`` array and return it normalised."""
    if not isinstance(creators, list):
        raise InvalidInputError("'creators' must be an array")

    valid = get_schema().get_item_type(item_type).creator_type_names
    normalised: list[dict[str, str]] = []

    for creator in creators:
        if not isinstance(creator, dict):
            raise InvalidInputError("Invalid creator")

        creator_type = creator.get("creatorType")
        if creator_type not in valid:
            raise InvalidInputError(
                f"'{creator_type}' is not a valid creator type for type '{item_type}'"
            )

        if "name" in creator:
            normalised.append({"creatorType": creator_type, "name": str(creator["name"])})
        else:
            normalised.append(
                {
                    "creatorType": creator_type,
                    "firstName": str(creator.get("firstName", "")),
                    "lastName": str(creator.get("lastName", "")),
                }
            )
    return normalised


def _validate_tags(tags: Any) -> list[tuple[str, int]]:
    """Check the ``tags`` array and return ``(name, type)`` pairs."""
    if not isinstance(tags, list):
        raise InvalidInputError("'tags' must be an array")

    result: list[tuple[str, int]] = []
    for tag in tags:
        if not isinstance(tag, dict) or "tag" not in tag:
            raise InvalidInputError("Invalid tag")
        name = str(tag["tag"])
        if not name:
            raise InvalidInputError("Tag cannot be empty")
        tag_type = int(tag.get("type", TagType.MANUAL))
        if tag_type not in (TagType.MANUAL, TagType.AUTOMATIC):
            raise InvalidInputError(f"Invalid tag type '{tag_type}'")
        result.append((name, tag_type))
    return result


def _validate_publications(
    payload: dict[str, Any],
    item_type: str,
    library_type: LibraryType,
    existing: Item | None,
) -> bool:
    """Return whether the item belongs to My Publications, refusing if it cannot.

    The checks and their order are upstream's: a falsy value is accepted
    without further question, and only a true one has to earn it.
    """
    if not payload.get("inPublications"):
        return False

    if library_type is not LibraryType.USER:
        raise InvalidInputError(
            f"{library_type.value.capitalize()} items cannot be added to My Publications"
        )

    is_child = bool(payload.get("parentItem")) or (existing is not None and existing.parent_id)
    if not is_child and item_type in NOTE_BEARING_TYPES:
        raise InvalidInputError(
            "Top-level notes and attachments cannot be added to My Publications"
        )

    if item_type == "attachment":
        link_mode = payload.get("linkMode")
        if link_mode is None and existing is not None:
            link_mode = existing.field_values().get("linkMode")
        if str(link_mode).lower() == "linked_file":
            raise InvalidInputError("Linked-file attachments cannot be added to My Publications")

    return True


def validate_item(
    payload: dict[str, Any],
    existing: Item | None = None,
    library_type: LibraryType = LibraryType.USER,
) -> dict[str, Any]:
    """Check an item's JSON against the schema and return its parts.

    Args:
        existing: The stored item, when the payload addresses one. An object
            that names an existing item and omits ``itemType`` is a partial
            update, and takes the type from that item.
        library_type: Which kind of library is being written to. Only a
            personal library has a My Publications.

    Raises:
        InvalidInputError: if the item type, a field or a creator type is not
            valid for this item.
    """
    item_type = payload.get("itemType")
    if not isinstance(item_type, str):
        if existing is None:
            raise InvalidInputError("'itemType' property not provided")
        item_type = existing.item_type

    schema = get_schema()
    type_ = schema.get_item_type(item_type)

    if (key := payload.get("key")) is not None and key != "" and not is_valid_key(str(key)):
        raise InvalidInputError(f"'{key}' is not a valid item key")

    unlisted = UNLISTED_FIELDS.get(item_type, frozenset())

    fields: dict[str, str] = {}
    for name, value in payload.items():
        if name in STRUCTURAL_KEYS:
            continue
        if name in unlisted:
            # `md5` and `mtime` are null in an empty template, and null means
            # absent rather than the string "None".
            if value is not None:
                fields[name] = str(value)
            continue
        if name not in schema.all_field_names:
            raise InvalidInputError(f"Invalid field '{name}'")
        if name not in type_.field_names:
            raise InvalidInputError(f"'{name}' is not a valid field for type '{item_type}'")
        fields[name] = "" if value is None else str(value)

    # Notes carry their content outside the schema's field list.
    if item_type in NOTE_BEARING_TYPES:
        fields["note"] = str(payload.get("note", ""))
    elif "note" in payload:
        raise InvalidInputError(f"'note' is not a valid field for type '{item_type}'")

    collections = payload.get("collections", [])
    if not isinstance(collections, list):
        raise InvalidInputError("'collections' must be an array")

    # Shared with collections, so both accept the empty array upstream allows
    # and both expand a predicate naming several objects.
    relations = parse_relations(payload)

    return {
        "item_type": item_type,
        "key": payload.get("key") or None,
        "version": payload.get("version"),
        "parent_item": payload.get("parentItem") or None,
        "fields": fields,
        "creators": _validate_creators(item_type, payload.get("creators", [])),
        "tags": _validate_tags(payload.get("tags", [])),
        "collections": [str(key) for key in collections],
        "relations": relations,
        "deleted": bool(payload.get("deleted", False)),
        "in_publications": _validate_publications(payload, item_type, library_type, existing),
        "date_added": _parse_timestamp(payload.get("dateAdded"), "dateAdded"),
        "date_modified": _parse_timestamp(payload.get("dateModified"), "dateModified"),
    }


async def _state(session: AsyncSession, item: Item) -> tuple[Any, ...]:
    """Everything about an item that a client can change.

    Deliberately excludes the version and ``serverDateModified``, which the
    server sets: comparing those would make every object look different. The
    sort keys are excluded too, being derived from the fields.

    The tags and collections come out of their link tables, so this has to be
    taken before those rows are rewritten -- an item whose tags were replaced
    but whose fields match is a change, and comparing only the scalars would
    miss it.
    """
    tags = await session.execute(
        select(Tag.name, Tag.type)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .where(ItemTag.item_id == item.id)
    )
    collections = await session.execute(
        select(Collection.key)
        .join(CollectionItem, CollectionItem.collection_id == Collection.id)
        .where(CollectionItem.item_id == item.id)
    )

    return (
        item.item_type,
        item.deleted,
        item.in_publications,
        item.date_added,
        item.date_modified,
        item.parent_id,
        tuple(sorted((field.field, field.value) for field in item.fields)),
        tuple(
            (
                creator.position,
                creator.creator_type,
                creator.first_name,
                creator.last_name,
                creator.name,
            )
            for creator in sorted(item.creators, key=lambda c: c.position)
        ),
        tuple(sorted((relation.predicate, relation.object) for relation in item.relations)),
        tuple(sorted(tags.all())),
        tuple(sorted(key for (key,) in collections.all())),
    )


async def _apply(
    session: AsyncSession,
    library: Library,
    item: Item,
    parsed: dict[str, Any],
    version: int,
    *,
    replace: bool,
) -> None:
    """Write ``parsed`` onto ``item``.

    Args:
        replace: Whether omitted properties are cleared. ``PUT`` replaces,
            ``PATCH`` leaves anything it does not mention alone.
    """
    item.item_type = parsed["item_type"]
    item.version = version
    item.deleted = parsed["deleted"]
    # A partial update leaves it alone; a replacing write means what it omits.
    if replace or "in_publications" in parsed:
        item.in_publications = parsed["in_publications"]

    # Client timestamps round-trip; the server's own is always now, which is what
    # makes sorting by `serverDateModified` trustworthy.
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    if parsed["date_added"] is not None:
        item.date_added = parsed["date_added"]
    elif item.date_added is None:
        item.date_added = now
    item.date_modified = parsed["date_modified"] or now
    item.server_date_modified = now

    if replace:
        item.fields = [
            ItemField(field=name, value=value) for name, value in parsed["fields"].items()
        ]
    else:
        existing = {field.field: field for field in item.fields}
        for name, value in parsed["fields"].items():
            if name in existing:
                existing[name].value = value
            else:
                item.fields.append(ItemField(field=name, value=value))

    if replace or parsed["creators"]:
        item.creators = [
            ItemCreator(
                position=index,
                creator_type=creator["creatorType"],
                first_name=creator.get("firstName"),
                last_name=creator.get("lastName"),
                name=creator.get("name"),
            )
            for index, creator in enumerate(parsed["creators"])
        ]

    if replace or parsed["relations"]:
        item.relations = [
            ItemRelation(predicate=predicate, object=obj) for predicate, obj in parsed["relations"]
        ]

    if parsed["parent_item"] is not None:
        parent = await get_item(session, library, str(parsed["parent_item"]))
        item.parent_id = parent.id
    elif replace:
        item.parent_id = None

    await session.flush()

    if replace or parsed["tags"]:
        await session.execute(delete(ItemTag).where(ItemTag.item_id == item.id))
        for name, tag_type in parsed["tags"]:
            tag = await resolve_tag(session, library, name, tag_type)
            tag.version = version
            session.add(ItemTag(item_id=item.id, tag_id=tag.id))

    if replace or parsed["collections"]:
        await session.execute(delete(CollectionItem).where(CollectionItem.item_id == item.id))
        for key in parsed["collections"]:
            collection = await session.scalar(
                select(Collection).where(Collection.library_id == library.id, Collection.key == key)
            )
            if collection is None:
                raise InvalidInputError(f"Collection {key} not found")
            session.add(CollectionItem(collection_id=collection.id, item_id=item.id))

    # Sort keys are recomputed from whatever the item now holds, so a PATCH that
    # changes only the title still reorders correctly.
    values = item.field_values()
    item.sort_title = itemdata.derive_sort_title(item.item_type, values)
    item.sort_creator = itemdata.derive_sort_creator(item.creators)
    item.sort_date = itemdata.derive_sort_date(item.item_type, values)


async def save_item(
    session: AsyncSession,
    library: Library,
    payload: dict[str, Any],
    version: int,
    *,
    key: str | None = None,
    replace: bool = True,
    require_version: bool = False,
    detect_unchanged: bool = False,
    actor_id: int | None = None,
) -> Item | None:
    """Create or update one item and return it.

    Args:
        version: Library version to stamp the item with.
        key: Key of the item being addressed, for key-based writes.
        replace: Whether omitted properties are cleared.
        require_version: Whether the payload must state the version it replaces.
        detect_unchanged: Return ``None`` when the payload describes what is
            already stored. The caller is expected to discard the work by
            rolling back, since applying it stamped a version onto the item.
        actor_id: Who is writing. Recorded in a group library so the item can
            say who added it and who last changed it.
    """
    # The item has to be resolved before validation, because an object naming an
    # existing item may omit properties that a new one must carry.
    target_key = key or (payload.get("key") if is_valid_key(str(payload.get("key", ""))) else None)

    item = None
    if target_key:
        item = await session.scalar(
            select(Item).where(Item.library_id == library.id, Item.key == str(target_key))
        )

    parsed = validate_item(payload, item, library.type)

    # An object that addresses an existing item without restating its type is a
    # diff against what the server already holds, so it must not clear the rest.
    if item is not None and "itemType" not in payload:
        replace = False
    # A new item has nothing to preserve, so writing it as a diff and writing it
    # as a replacement describe the same result. It is written as a replacement
    # because that assigns the field, creator and relation collections rather
    # than reading them, and reading an unloaded collection off a row that has
    # just been flushed is a lazy load -- which under async SQLAlchemy is a
    # `MissingGreenlet` rather than a query. `save_collection` and `save_search`
    # reach the same place by treating an object as partial only when it names
    # one that exists.
    if item is None:
        replace = True

    before = None
    creating = item is None
    if item is None:
        if require_version and parsed["version"]:
            raise NotFoundError("Not found")
        item = Item(
            library_id=library.id,
            key=coerce_key(str(target_key) if target_key else None),
            version=version,
        )
        session.add(item)
    else:
        check_object_version(item.version, parsed["version"], required=require_version)
        if detect_unchanged:
            before = await _state(session, item)

    await _apply(session, library, item, parsed, version, replace=replace)

    if before is not None and before == await _state(session, item):
        return None

    # After the unchanged check, so re-sending an item exactly as stored does
    # not rewrite who last touched it. Upstream reaches the same place from the
    # other direction: nothing is written, so its `groupItems` update never
    # runs.
    if library.type is LibraryType.GROUP and actor_id is not None:
        if creating:
            # Upstream inserts both columns on create, and its serialiser then
            # collapses them because they are equal.
            item.created_by_user_id = actor_id
        item.last_modified_by_user_id = actor_id

    return item


async def _delete_one(session: AsyncSession, library: Library, item: Item, version: int) -> None:
    """Remove one item, its children, and the rows that point at it."""
    # A note or attachment cannot outlive its parent: it has nothing left to
    # attach to, and the row it points at would be gone.
    children = await session.scalars(select(Item).where(Item.parent_id == item.id))
    for child in list(children):
        await _delete_one(session, library, child, version)

    tag_ids = list(await session.scalars(select(ItemTag.tag_id).where(ItemTag.item_id == item.id)))
    await session.execute(delete(ItemTag).where(ItemTag.item_id == item.id))
    await session.execute(delete(CollectionItem).where(CollectionItem.item_id == item.id))
    key = item.key
    await session.delete(item)
    await session.flush()

    await _drop_unused_tags(session, tag_ids)
    await record_deletion(session, library, DeletedObjectType.ITEM, key, version)


async def _drop_unused_tags(session: AsyncSession, tag_ids: list[int]) -> None:
    """Remove tags that no item carries any more.

    A tag exists only through its items, so one left with none is invisible over
    the API; without this the row would linger.
    """
    for tag_id in tag_ids:
        still_used = await session.scalar(
            select(ItemTag.item_id).where(ItemTag.tag_id == tag_id).limit(1)
        )
        if still_used is None:
            await session.execute(delete(Tag).where(Tag.id == tag_id))


async def delete_items(
    session: AsyncSession,
    library: Library,
    keys: list[str],
    version: int,
) -> None:
    """Remove items outright and record the deletions for ``/deleted``."""
    for key in keys:
        item = await session.scalar(
            select(Item).where(Item.library_id == library.id, Item.key == key)
        )
        if item is None:
            # Deleting something already gone is not an error.
            continue
        await _delete_one(session, library, item, version)
