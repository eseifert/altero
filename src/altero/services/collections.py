"""Reading collections out of a library."""

from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Collection, CollectionItem, Item, Library
from altero.query import Direction, ListQuery
from altero.services.items import Page, paginate

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
        Collection.deleted.is_(False),
    ]

    if top_only:
        filters.append(Collection.parent_id.is_(None))
    if parent_key is not None:
        parent = await get_collection(session, library, parent_key)
        filters.append(Collection.parent_id == parent.id)
    if query.since:
        filters.append(Collection.version > query.since)

    statement = select(Collection).where(and_(*filters))
    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    result = await session.scalars(paginate(_apply_sort(statement, query), query))

    return Page(objects=list(result), total=total or 0, library_version=library.version)


async def count_subcollections(session: AsyncSession, collection: Collection) -> int:
    """Return how many collections sit directly inside ``collection``."""
    total = await session.scalar(
        select(func.count())
        .select_from(Collection)
        .where(Collection.parent_id == collection.id, Collection.deleted.is_(False))
    )
    return total or 0


async def count_items(session: AsyncSession, collection: Collection) -> int:
    """Return how many non-trashed top-level items ``collection`` holds."""
    total = await session.scalar(
        select(func.count())
        .select_from(CollectionItem)
        .join(Item, Item.id == CollectionItem.item_id)
        .where(
            CollectionItem.collection_id == collection.id,
            Item.deleted.is_(False),
            Item.parent_id.is_(None),
        )
    )
    return total or 0


async def parent_key_of(session: AsyncSession, collection: Collection) -> str | None:
    """Return the key of ``collection``'s parent, if it has one."""
    if collection.parent_id is None:
        return None
    parent = await session.get(Collection, collection.parent_id)
    return parent.key if parent else None
