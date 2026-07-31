"""Reading tags out of a library.

Tags are counted and filtered against a set of items, so the same code serves
``/tags`` and the tag listings scoped to an item, a collection or the trash.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Item, ItemTag, Library, Tag
from altero.query import Direction, ListQuery, TagSearchMode
from altero.services.items import Page, paginate


@dataclass(frozen=True, slots=True)
class TagSummary:
    """A tag together with the counts the response reports."""

    name: str
    type: int
    num_items: int
    version: int


def _name_filter(query: ListQuery) -> ColumnElement[bool] | None:
    """Return the predicate for a quick search over tag names."""
    if not query.q:
        return None
    if query.qmode == TagSearchMode.STARTS_WITH:
        return Tag.name.ilike(f"{query.q}%")
    return Tag.name.ilike(f"%{query.q}%")


def _apply_sort(statement: Select[Any], query: ListQuery, count: Any) -> Select[Any]:
    column = count if query.sort == "numItems" else Tag.name
    ordering = column.desc() if query.direction is Direction.DESCENDING else column.asc()
    return statement.order_by(ordering, Tag.name.asc())


async def list_tags(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    *,
    item_scope: Select[Any] | None = None,
) -> Page[TagSummary]:
    """Return one page of tags.

    Args:
        item_scope: A ``SELECT`` of item ids the tags must be attached to. When
            omitted, every tag in the library is considered.
    """
    filters: list[ColumnElement[bool]] = [Tag.library_id == library.id]
    if query.since:
        filters.append(Tag.version > query.since)
    if (name_filter := _name_filter(query)) is not None:
        filters.append(name_filter)

    join_filters = list(filters)
    if item_scope is not None:
        join_filters.append(ItemTag.item_id.in_(item_scope))

    count = func.count(ItemTag.item_id).label("num_items")
    statement = (
        select(Tag.name, Tag.type, count, Tag.version)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .where(and_(*join_filters))
        .group_by(Tag.id, Tag.name, Tag.type, Tag.version)
    )

    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    result = await session.execute(paginate(_apply_sort(statement, query, count), query))

    summaries = [
        TagSummary(name=name, type=tag_type or 0, num_items=num_items, version=version)
        for name, tag_type, num_items, version in result.all()
    ]
    return Page(objects=summaries, total=total or 0, library_version=library.version)


async def get_tag(session: AsyncSession, library: Library, name: str) -> TagSummary:
    """Return one tag by name."""
    row = (
        await session.execute(
            select(Tag.name, Tag.type, func.count(ItemTag.item_id), Tag.version)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(Tag.library_id == library.id, Tag.name == name)
            .group_by(Tag.id, Tag.name, Tag.type, Tag.version)
        )
    ).first()

    if row is None:
        raise NotFoundError("Tag not found")

    tag_name, tag_type, num_items, version = row
    return TagSummary(name=tag_name, type=tag_type or 0, num_items=num_items, version=version)


def items_in_library(library: Library) -> Select[Any]:
    """Return a ``SELECT`` of every non-trashed item id in ``library``."""
    return select(Item.id).where(Item.library_id == library.id, Item.deleted.is_(False))
