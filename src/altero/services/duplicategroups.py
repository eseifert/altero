"""Page complete duplicate groups for the browser's review list."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import id_list
from altero.models import Item, Library
from altero.query import ListQuery
from altero.services import duplicates, items
from altero.services.auth import Access


@dataclass
class GroupPage:
    groups: list[list[Item]]
    total: int
    total_groups: int
    library_version: int


async def matching_groups(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    scope: items.Scope,
    collection: str | None = None,
    *,
    permit: Access | None = None,
) -> list[tuple[int, ...]]:
    """Find complete permitted groups, ordered by their first matching member.

    The query's page bounds are ignored. Members retain the finder's oldest-first
    order, independently of the requested sort.
    """
    groups = await duplicates.duplicate_item_groups(session, library)
    matching = await items.ordered_item_ids(
        session, library, query, scope, collection, permit=permit
    )
    rank = {item_id: index for index, item_id in enumerate(matching)}
    allowed_query = await items.build_item_query(
        session, library, ListQuery(), items.Scope.TOP, permit=permit
    )
    candidates = {item_id for group in groups for item_id in group}
    allowed = set(
        await session.scalars(
            allowed_query.with_only_columns(Item.id).where(Item.id.in_(id_list(candidates)))
        )
    )
    visible = [tuple(item_id for item_id in group if item_id in allowed) for group in groups]
    found = [
        group for group in visible if len(group) > 1 and any(item_id in rank for item_id in group)
    ]
    found.sort(key=lambda group: min(rank[item_id] for item_id in group if item_id in rank))
    return found


async def list_groups(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    scope: items.Scope,
    collection: str | None = None,
    *,
    permit: Access | None = None,
) -> GroupPage:
    """Filters find groups; members remain complete within the reader's access.

    Group order follows the first matching item in the requested sort. Members
    retain the finder's oldest-first order, independently of that sort. Offsets
    and limits count groups, so neither filtering nor paging can split one.
    """
    found = await matching_groups(session, library, query, scope, collection, permit=permit)
    page = found[query.start : query.start + query.limit]
    page_ids = [item_id for group in page for item_id in group]
    loaded = {
        item.id: item
        for item in await session.scalars(
            select(Item).where(Item.library_id == library.id, Item.id.in_(id_list(page_ids)))
        )
    }
    return GroupPage(
        groups=[[loaded[item_id] for item_id in group] for group in page],
        total=sum(len(group) for group in found),
        total_groups=len(found),
        library_version=library.version,
    )
