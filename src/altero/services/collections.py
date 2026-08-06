"""Reading collections out of a library."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Collection, CollectionItem, Item, Library
from altero.query import Direction, ListQuery
from altero.services.items import Page, count_matches, paginate

#: Sort parameters that map straight onto a column of ``collections``.
_COLUMN_SORTS = {
    "title": Collection.name,
    "name": Collection.name,
    "dateAdded": Collection.key,
    "dateModified": Collection.version,
}


def _apply_sort(statement: Select[Any], query: ListQuery) -> Select[Any]:
    # Collections carry no timestamps of their own, so a request to sort by one
    # falls back to the version, which moves in the same direction.
    column = _COLUMN_SORTS.get(query.sort, Collection.name)
    ordering = column.desc() if query.direction is Direction.DESCENDING else column.asc()
    return statement.order_by(ordering, Collection.key.asc())


async def get_collection(session: AsyncSession, library: Library, key: str) -> Collection:
    """Return one collection by key."""
    collection = await session.scalar(
        select(Collection).where(Collection.library_id == library.id, Collection.key == key)
    )
    if collection is None:
        raise NotFoundError("Collection not found")
    return collection


async def list_collections(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    *,
    top_only: bool = False,
    parent_key: str | None = None,
) -> Page[Collection]:
    """Return one page of collections.

    Args:
        top_only: Restrict to collections without a parent.
        parent_key: Restrict to the direct children of this collection.
    """
    filters: list[ColumnElement[bool]] = [
        Collection.library_id == library.id,
    ]

    if top_only:
        filters.append(Collection.parent_id.is_(None))
    if parent_key is not None:
        parent = await get_collection(session, library, parent_key)
        filters.append(Collection.parent_id == parent.id)
    if query.since:
        filters.append(Collection.version > query.since)
    if query.collection_keys:
        # How the client fetches the collections it has just been told changed.
        # `Zotero_Collections::search` adds the same `key IN (...)`.
        filters.append(Collection.key.in_(query.collection_keys))

    statement = select(Collection).where(and_(*filters))
    result = await session.scalars(paginate(_apply_sort(statement, query), query))
    objects = list(result)

    return Page(
        objects=objects,
        total=await count_matches(session, statement, query, len(objects)),
        library_version=library.version,
    )


async def count_subcollections(
    session: AsyncSession, collections: Sequence[Collection]
) -> dict[int, int]:
    """Return how many collections sit directly inside each of ``collections``.

    Keyed by collection id, with the empty ones absent, as the item helpers do.
    """
    if not collections:
        return {}

    result = await session.execute(
        select(Collection.parent_id, func.count())
        .where(
            Collection.parent_id.in_([collection.id for collection in collections]),
        )
        .group_by(Collection.parent_id)
    )
    return {parent_id: count for parent_id, count in result.all()}


async def count_items(session: AsyncSession, collections: Sequence[Collection]) -> dict[int, int]:
    """Return how many non-trashed top-level items each of ``collections`` holds."""
    if not collections:
        return {}

    result = await session.execute(
        select(CollectionItem.collection_id, func.count())
        .join(Item, Item.id == CollectionItem.item_id)
        .where(
            CollectionItem.collection_id.in_([collection.id for collection in collections]),
            Item.deleted.is_(False),
            Item.parent_id.is_(None),
        )
        .group_by(CollectionItem.collection_id)
    )
    return {collection_id: count for collection_id, count in result.all()}


async def parent_keys_for(
    session: AsyncSession, collections: Sequence[Collection]
) -> dict[int, str]:
    """Return the key of every parent named by ``collections``, by parent id.

    A page of top-level collections names none, and so costs no query.
    """
    parent_ids = {
        collection.parent_id for collection in collections if collection.parent_id is not None
    }
    if not parent_ids:
        return {}

    result = await session.execute(
        select(Collection.id, Collection.key).where(Collection.id.in_(parent_ids))
    )
    return {collection_id: key for collection_id, key in result.all()}
