"""Reading tags out of a library.

Tags are counted and filtered against a set of items, so the same code serves
``/tags`` and the tag listings scoped to an item, a collection or the trash.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Item, ItemTag, Library, Tag
from altero.query import Direction, ListQuery, TagSearchMode
from altero.services.auth import Access
from altero.services.items import (
    Page,
    confined_to_collections,
    count_matches,
    paginate,
)


@dataclass(frozen=True, slots=True)
class TagSummary:
    """A tag together with the counts the response reports."""

    name: str
    type: int
    num_items: int
    version: int
    #: When an item carrying this tag last changed, which is the only sense in
    #: which a tag has a modification time of its own. Atom entries need one;
    #: the JSON shape of a tag does not carry it.
    last_modified: datetime | None = None


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
    permit: Access | None = None,
) -> Page[TagSummary]:
    """Return one page of tags.

    Args:
        item_scope: A ``SELECT`` of item ids the tags must be attached to. When
            omitted, every tag in the library is considered.
        permit: What the caller may see. A tag has no existence apart from the
            items carrying it, so a resource-scoped grant narrows the *items*
            the count runs over -- and a tag left carrying none of them stops
            existing, which is what keeps the library's tag list from
            describing the collections the grant excluded. The listing scoped
            to an item set gets this through ``item_scope`` as well; both are
            applied, and neither can widen the other.
    """
    filters: list[ColumnElement[bool]] = [Tag.library_id == library.id]
    if query.since:
        filters.append(Tag.version > query.since)
    if (name_filter := _name_filter(query)) is not None:
        filters.append(name_filter)

    join_filters = list(filters)
    if item_scope is not None:
        join_filters.append(ItemTag.item_id.in_(item_scope))
    if permit is not None and permit.collections is not None:
        join_filters.append(confined_to_collections(permit.collections))

    count = func.count(ItemTag.item_id).label("num_items")
    statement = (
        select(Tag.name, Tag.type, count, Tag.version, func.max(Item.server_date_modified))
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .join(Item, Item.id == ItemTag.item_id)
        .where(and_(*join_filters))
        .group_by(Tag.id, Tag.name, Tag.type, Tag.version)
    )

    result = await session.execute(paginate(_apply_sort(statement, query, count), query))

    summaries = [
        TagSummary(
            name=name,
            type=tag_type or 0,
            num_items=num_items,
            version=version,
            last_modified=modified,
        )
        for name, tag_type, num_items, version, modified in result.all()
    ]
    return Page(
        objects=summaries,
        total=await count_matches(session, statement, query, len(summaries)),
        library_version=library.version,
    )


async def get_tag(
    session: AsyncSession, library: Library, name: str, *, permit: Access | None = None
) -> TagSummary:
    """Return one tag by name.

    A tag carried by nothing the caller may see is *not found*, which is the
    same answer a tag nobody has typed gets: the count would otherwise be zero
    and the tag would still be there, saying that something outside the grant
    carries it.
    """
    filters: list[ColumnElement[bool]] = [Tag.library_id == library.id, Tag.name == name]
    if permit is not None and permit.collections is not None:
        filters.append(confined_to_collections(permit.collections))

    row = (
        await session.execute(
            select(
                Tag.name,
                Tag.type,
                func.count(ItemTag.item_id),
                Tag.version,
                func.max(Item.server_date_modified),
            )
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .join(Item, Item.id == ItemTag.item_id)
            .where(and_(*filters))
            .group_by(Tag.id, Tag.name, Tag.type, Tag.version)
        )
    ).first()

    if row is None:
        raise NotFoundError("Tag not found")

    tag_name, tag_type, num_items, version, modified = row
    return TagSummary(
        name=tag_name,
        type=tag_type or 0,
        num_items=num_items,
        version=version,
        last_modified=modified,
    )


def items_in_library(library: Library) -> Select[Any]:
    """Return a ``SELECT`` of every non-trashed item id in ``library``."""
    return select(Item.id).where(Item.library_id == library.id, Item.deleted.is_(False))
