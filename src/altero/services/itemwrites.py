"""Creating, updating and deleting items."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
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
    Tag,
    TagType,
)
from altero.services import itemdata
from altero.services.deletions import record_deletion
from altero.services.items import get_item
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
        {"linkMode", "contentType", "charset", "filename", "md5", "mtime", "path"}
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


def validate_item(payload: dict[str, Any]) -> dict[str, Any]:
    """Check an item's JSON against the schema and return its parts.

    Raises:
        InvalidInputError: if the item type, a field or a creator type is not
            valid for this item.
    """
    item_type = payload.get("itemType")
    if not isinstance(item_type, str):
        raise InvalidInputError("'itemType' property not provided")

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

    relations = payload.get("relations", {})
    if not isinstance(relations, dict):
        raise InvalidInputError("'relations' must be an object")

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
        "date_added": _parse_timestamp(payload.get("dateAdded"), "dateAdded"),
        "date_modified": _parse_timestamp(payload.get("dateModified"), "dateModified"),
    }


async def _resolve_tag(session: AsyncSession, library: Library, name: str, type_: int) -> Tag:
    """Return the tag with this name and type, creating it if needed.

    Two requests can reach this at once with the same new tag. Rather than
    trusting the gap between looking and inserting, the unique constraint on
    (library, name, type) decides: whoever loses the race reads back the row the
    winner wrote.
    """
    lookup = select(Tag).where(Tag.library_id == library.id, Tag.name == name, Tag.type == type_)

    tag = await session.scalar(lookup)
    if tag is not None:
        return tag

    try:
        async with session.begin_nested():
            tag = Tag(library_id=library.id, key=coerce_key(None), name=name, type=type_)
            session.add(tag)
            await session.flush()
    except IntegrityError:
        tag = await session.scalar(lookup)
        if tag is None:  # pragma: no cover - the constraint fired for another reason
            raise
    return tag


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
            ItemRelation(predicate=predicate, object=str(obj))
            for predicate, objects in parsed["relations"].items()
            for obj in (objects if isinstance(objects, list) else [objects])
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
            tag = await _resolve_tag(session, library, name, tag_type)
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
) -> Item:
    """Create or update one item and return it.

    Args:
        version: Library version to stamp the item with.
        key: Key of the item being addressed, for key-based writes.
        replace: Whether omitted properties are cleared.
        require_version: Whether the payload must state the version it replaces.
    """
    parsed = validate_item(payload)
    target_key = key or parsed["key"]

    item = None
    if target_key:
        item = await session.scalar(
            select(Item).where(Item.library_id == library.id, Item.key == target_key)
        )

    if item is None:
        if require_version and parsed["version"]:
            raise NotFoundError("Not found")
        item = Item(library_id=library.id, key=coerce_key(target_key), version=version)
        session.add(item)
    else:
        check_object_version(item.version, parsed["version"], required=require_version)

    await _apply(session, library, item, parsed, version, replace=replace)
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
