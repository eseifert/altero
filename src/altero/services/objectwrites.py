"""Creating, updating and deleting collections, saved searches and tags."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError
from altero.keys import coerce_key, is_valid_key
from altero.models import (
    Collection,
    CollectionItem,
    CollectionRelation,
    DeletedObjectType,
    ItemTag,
    Library,
    SavedSearch,
    SearchCondition,
    Tag,
)
from altero.services.collections import get_collection
from altero.services.deletions import record_deletion
from altero.services.writes import check_object_version


def parse_relations(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return a ``relations`` map as predicate-object pairs.

    A predicate may name one object or several, so a string and a list both
    arrive here and leave as pairs. An empty array is accepted in place of an
    empty object, which upstream allows explicitly "because it's annoying for
    some clients otherwise".
    """
    relations = payload.get("relations", {})
    if isinstance(relations, list) and not relations:
        return []
    if not isinstance(relations, dict):
        raise InvalidInputError("'relations' property must be an object")

    pairs: list[tuple[str, str]] = []
    for predicate, objects in relations.items():
        for obj in objects if isinstance(objects, list) else [objects]:
            pairs.append((str(predicate), str(obj)))
    return pairs


def parse_deleted(payload: dict[str, Any]) -> bool:
    """Return the trash flag, rejecting anything that is not a boolean.

    Zotero trashes a collection or a saved search by setting this rather than
    by deleting the object, so it has to round-trip like any other property.
    Upstream accepts ``true``/``false`` and the integers 0 and 1, and refuses
    everything else -- a string "false" would otherwise be read as trashed.
    """
    value = payload.get("deleted", False)
    if not isinstance(value, bool) and value not in (0, 1):
        raise InvalidInputError("'deleted' must be a boolean")
    return bool(value)


def _collection_state(collection: Collection) -> tuple[Any, ...]:
    """Everything about a collection that a client can change."""
    return (
        collection.name,
        collection.parent_id,
        collection.deleted,
        tuple(sorted((r.predicate, r.object) for r in collection.relations)),
    )


def _search_state(search: SavedSearch) -> tuple[Any, ...]:
    return (
        search.name,
        search.deleted,
        tuple(
            (condition.position, condition.condition, condition.operator, condition.value)
            for condition in sorted(search.conditions, key=lambda c: c.position)
        ),
    )


def _check_key(payload: dict[str, Any], label: str) -> str | None:
    key = payload.get("key")
    if key is None or key == "":
        return None
    if not is_valid_key(str(key)):
        raise InvalidInputError(f"'{key}' is not a valid {label} key")
    return str(key)


async def save_collection(
    session: AsyncSession,
    library: Library,
    payload: dict[str, Any],
    version: int,
    *,
    key: str | None = None,
    require_version: bool = False,
    detect_unchanged: bool = False,
) -> Collection | None:
    """Create or update one collection.

    Args:
        detect_unchanged: Return ``None`` instead of writing when the payload
            describes what is already stored. Only the multi-object path asks
            for this, because only its response has somewhere to report it.
    """
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise InvalidInputError("'name' property not provided")

    target_key = key or _check_key(payload, "collection")

    collection = None
    if target_key:
        collection = await session.scalar(
            select(Collection).where(
                Collection.library_id == library.id, Collection.key == target_key
            )
        )

    before = None
    if collection is None:
        collection = Collection(library_id=library.id, key=coerce_key(target_key), version=version)
        session.add(collection)
    else:
        check_object_version(collection.version, payload.get("version"), required=require_version)
        if detect_unchanged:
            before = _collection_state(collection)

    collection.name = name
    collection.version = version
    collection.deleted = parse_deleted(payload)
    collection.relations = [
        CollectionRelation(predicate=predicate, object=obj)
        for predicate, obj in parse_relations(payload)
    ]

    # `parentCollection` is false or absent for a top-level collection.
    parent = payload.get("parentCollection")
    if parent:
        if str(parent) == collection.key:
            raise InvalidInputError("Collection cannot be its own parent")
        parent_collection = await get_collection(session, library, str(parent))
        collection.parent_id = parent_collection.id
    else:
        collection.parent_id = None

    if before is not None and before == _collection_state(collection):
        return None

    await session.flush()
    return collection


async def delete_collections(
    session: AsyncSession, library: Library, keys: list[str], version: int
) -> None:
    """Remove collections and record the deletions."""
    for key in keys:
        collection = await session.scalar(
            select(Collection).where(Collection.library_id == library.id, Collection.key == key)
        )
        if collection is None:
            continue

        # Nested collections are promoted rather than removed with the parent,
        # which is what the client expects when a collection is deleted.
        children = await session.scalars(
            select(Collection).where(Collection.parent_id == collection.id)
        )
        for child in children:
            child.parent_id = collection.parent_id
            child.version = version

        await session.execute(
            delete(CollectionItem).where(CollectionItem.collection_id == collection.id)
        )
        await session.delete(collection)
        await record_deletion(session, library, DeletedObjectType.COLLECTION, key, version)


async def save_search(
    session: AsyncSession,
    library: Library,
    payload: dict[str, Any],
    version: int,
    *,
    key: str | None = None,
    require_version: bool = False,
    detect_unchanged: bool = False,
) -> SavedSearch | None:
    """Create or update one saved search.

    Args:
        detect_unchanged: Return ``None`` rather than writing when the payload
            matches what is stored.
    """
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise InvalidInputError("'name' property not provided")

    raw_conditions = payload.get("conditions", [])
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise InvalidInputError("'conditions' property not provided")

    conditions: list[tuple[str, str, str]] = []
    for condition in raw_conditions:
        if not isinstance(condition, dict) or not condition.get("condition"):
            raise InvalidInputError("Invalid search condition")
        conditions.append(
            (
                str(condition["condition"]),
                str(condition.get("operator", "")),
                str(condition.get("value", "")),
            )
        )

    target_key = key or _check_key(payload, "search")

    search = None
    if target_key:
        search = await session.scalar(
            select(SavedSearch).where(
                SavedSearch.library_id == library.id, SavedSearch.key == target_key
            )
        )

    before = None
    if search is None:
        search = SavedSearch(library_id=library.id, key=coerce_key(target_key), version=version)
        session.add(search)
    else:
        check_object_version(search.version, payload.get("version"), required=require_version)
        if detect_unchanged:
            before = _search_state(search)

    desired = tuple(
        (index, condition, operator, value)
        for index, (condition, operator, value) in enumerate(conditions)
    )
    deleted = parse_deleted(payload)
    if before is not None and before == (name, deleted, desired):
        # Compared before the conditions are replaced: assigning the list would
        # delete and reinsert every row to arrive at what is already there.
        return None

    search.name = name
    search.version = version
    search.deleted = deleted
    search.conditions = [
        SearchCondition(position=index, condition=condition, operator=operator, value=value)
        for index, condition, operator, value in desired
    ]

    await session.flush()
    return search


async def delete_searches(
    session: AsyncSession, library: Library, keys: list[str], version: int
) -> None:
    """Remove saved searches and record the deletions."""
    for key in keys:
        search = await session.scalar(
            select(SavedSearch).where(SavedSearch.library_id == library.id, SavedSearch.key == key)
        )
        if search is None:
            continue
        await session.delete(search)
        await record_deletion(session, library, DeletedObjectType.SEARCH, key, version)


async def delete_tags(
    session: AsyncSession, library: Library, names: list[str], version: int
) -> None:
    """Remove tags by name, detaching them from every item first.

    A name may exist twice, once manual and once automatic, and deleting by name
    removes both.
    """
    for name in names:
        tags = await session.scalars(
            select(Tag).where(Tag.library_id == library.id, Tag.name == name)
        )
        removed = False
        for tag in tags:
            await session.execute(delete(ItemTag).where(ItemTag.tag_id == tag.id))
            await session.delete(tag)
            removed = True

        if removed:
            await record_deletion(session, library, DeletedObjectType.TAG, name, version)
