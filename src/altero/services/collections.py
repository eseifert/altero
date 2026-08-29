"""Reading collections out of a library."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Collection, CollectionItem, Item, Library
from altero.query import Direction, ListQuery
from altero.services.auth import Access
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


async def get_collection(
    session: AsyncSession, library: Library, key: str, *, permit: Access | None = None
) -> Collection:
    """Return one collection by key.

    A collection outside a resource-scoped grant is *not found*, the way a
    withheld note is: a refusal that named it would confirm it exists, and the
    key is the only thing the caller had. This is the one door every path to a
    single collection goes through, its subcollections and its items included.
    """
    collection = await session.scalar(
        select(Collection).where(Collection.library_id == library.id, Collection.key == key)
    )
    if collection is None:
        raise NotFoundError("Collection not found")
    if (
        permit is not None
        and permit.collections is not None
        and collection.id not in permit.collections
    ):
        raise NotFoundError("Collection not found")
    return collection


async def subtree(session: AsyncSession, collection: Collection) -> list[Collection]:
    """Return ``collection`` and every collection nested inside it, at any depth.

    Walked a level at a time rather than with a recursive CTE, which SQLite and
    PostgreSQL spell differently enough to be worth avoiding for a tree that is
    a handful of levels deep in every real library. The walk cannot loop:
    ``webcollections`` refuses a move that would close one, and a collection
    already seen is not descended into a second time.
    """
    found = {collection.id: collection}
    frontier = [collection.id]

    while frontier:
        children = list(
            await session.scalars(select(Collection).where(Collection.parent_id.in_(frontier)))
        )
        frontier = [child.id for child in children if child.id not in found]
        found.update({child.id: child for child in children})

    return list(found.values())


async def list_collections(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    *,
    top_only: bool = False,
    parent_key: str | None = None,
    permit: Access | None = None,
) -> Page[Collection]:
    """Return one page of collections.

    Args:
        top_only: Restrict to collections without a parent.
        parent_key: Restrict to the direct children of this collection.
        permit: What the caller may see. A resource-scoped grant is filtered
            here, which covers the listing, the keys, the versions and the
            totals in one clause.
    """
    filters: list[ColumnElement[bool]] = [
        Collection.library_id == library.id,
    ]

    if permit is not None and permit.collections is not None:
        filters.append(Collection.id.in_(permit.collections))
        if top_only:
            # "Top" means top *of what the caller can see*. A granted collection
            # nested three deep would otherwise never appear in any listing: it
            # has a parent, and its parent is not in the grant. So a collection
            # is top-level here when its own parent is out of reach, which is
            # what the caller's tree actually looks like.
            filters.append(
                or_(
                    Collection.parent_id.is_(None),
                    Collection.parent_id.not_in(permit.collections),
                )
            )
    elif top_only:
        filters.append(Collection.parent_id.is_(None))

    if parent_key is not None:
        parent = await get_collection(session, library, parent_key, permit=permit)
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
