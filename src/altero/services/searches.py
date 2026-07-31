"""Reading saved searches out of a library."""

from typing import Any

from sqlalchemy import ColumnElement, Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Library, SavedSearch
from altero.query import Direction, ListQuery
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


async def get_search(session: AsyncSession, library: Library, key: str) -> SavedSearch:
    """Return one saved search by key."""
    search = await session.scalar(
        select(SavedSearch).where(SavedSearch.library_id == library.id, SavedSearch.key == key)
    )
    if search is None:
        raise NotFoundError("Search not found")
    return search


async def list_searches(
    session: AsyncSession, library: Library, query: ListQuery
) -> Page[SavedSearch]:
    """Return one page of saved searches."""
    filters: list[ColumnElement[bool]] = [
        SavedSearch.library_id == library.id,
        SavedSearch.deleted.is_(False),
    ]
    if query.since:
        filters.append(SavedSearch.version > query.since)

    statement = select(SavedSearch).where(and_(*filters))
    result = await session.scalars(paginate(_apply_sort(statement, query), query))
    objects = list(result)

    return Page(
        objects=objects,
        total=await count_matches(session, statement, query, len(objects)),
        library_version=library.version,
    )
