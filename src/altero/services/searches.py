"""Reading saved searches out of a library."""

from typing import Any

from sqlalchemy import ColumnElement, Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Library, SavedSearch
from altero.query import Direction, ListQuery
from altero.services.auth import Access
from altero.services.items import Page, count_matches, paginate

_COLUMN_SORTS = {
    "title": SavedSearch.name,
    "name": SavedSearch.name,
    "dateAdded": SavedSearch.key,
    "dateModified": SavedSearch.version,
}


def _apply_sort(statement: Select[Any], query: ListQuery) -> Select[Any]:
    column = _COLUMN_SORTS.get(query.sort, SavedSearch.name)
    ordering = column.desc() if query.direction is Direction.DESCENDING else column.asc()
    return statement.order_by(ordering, SavedSearch.key.asc())


async def get_search(
    session: AsyncSession, library: Library, key: str, *, permit: Access | None = None
) -> SavedSearch:
    """Return one saved search by key.

    A confined credential finds none. See :func:`list_searches`.
    """
    if permit is not None and permit.collections is not None:
        raise NotFoundError("Search not found")

    search = await session.scalar(
        select(SavedSearch).where(SavedSearch.library_id == library.id, SavedSearch.key == key)
    )
    if search is None:
        raise NotFoundError("Search not found")
    return search


async def list_searches(
    session: AsyncSession, library: Library, query: ListQuery, *, permit: Access | None = None
) -> Page[SavedSearch]:
    """Return one page of saved searches.

    A credential confined to some collections sees no saved searches at all,
    and that is a decision rather than an omission. A saved search is a set of
    conditions over the whole library: its name and its terms describe items
    the confinement was drawn to exclude, and altero does not run one server
    side, so there is nothing to intersect with the grant. The honest answer to
    "which of these does this application reach" is none of them.
    ``docs/compatibility.md`` records it.
    """
    if permit is not None and permit.collections is not None:
        return Page(objects=[], total=0, library_version=library.version)

    filters: list[ColumnElement[bool]] = [
        SavedSearch.library_id == library.id,
    ]
    if query.since:
        filters.append(SavedSearch.version > query.since)
    if query.search_keys:
        filters.append(SavedSearch.key.in_(query.search_keys))

    statement = select(SavedSearch).where(and_(*filters))
    result = await session.scalars(paginate(_apply_sort(statement, query), query))
    objects = list(result)

    return Page(
        objects=objects,
        total=await count_matches(session, statement, query, len(objects)),
        library_version=library.version,
    )
