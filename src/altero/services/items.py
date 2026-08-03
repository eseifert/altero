"""Reading items out of a library."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.itemschema import get_schema
from altero.models import (
    Collection,
    CollectionItem,
    Item,
    ItemField,
    ItemTag,
    Library,
    Tag,
)
from altero.pagination import UNLIMITED
from altero.query import Direction, ListQuery, QuickSearchMode
from altero.search import SearchExpression

#: Fields consulted by a ``titleCreatorYear`` quick search, via the sort keys
#: that already hold each item type's title, creator and date.
_QUICK_SEARCH_COLUMNS = (Item.sort_title, Item.sort_creator, Item.sort_date)

#: Sort parameters that map straight onto a column of ``items``.
_COLUMN_SORTS = {
    "dateAdded": Item.date_added,
    "dateModified": Item.date_modified,
    "itemType": Item.item_type,
    "title": Item.sort_title,
    "creator": Item.sort_creator,
    "date": Item.sort_date,
}


class Scope(StrEnum):
    """Which slice of a library an item listing covers."""

    ALL = auto()
    TOP = auto()
    TRASH = auto()
    CHILDREN = auto()
    COLLECTION = auto()
    COLLECTION_TOP = auto()
    #: The owner's My Publications, which is a public view of one library.
    PUBLICATIONS = auto()
    PUBLICATIONS_TOP = auto()


def paginate(statement: Select[Any], query: ListQuery) -> Select[Any]:
    """Apply ``start`` and ``limit``, omitting LIMIT when the page is unlimited.

    ``format=keys`` and ``format=versions`` default to unlimited, so the whole
    result set comes back in one response.
    """
    statement = statement.offset(query.start) if query.start else statement
    return statement if query.limit == UNLIMITED else statement.limit(query.limit)


async def count_matches(
    session: AsyncSession,
    statement: Select[Any],
    query: ListQuery,
    returned: int,
) -> int:
    """Return how many objects ``statement`` matches, for ``Total-Results``.

    An unlimited page holds every match from ``start`` onwards, so the total is
    already known and counting again would scan the library a second time. That
    is the ``format=keys`` and ``format=versions`` case, which is what a syncing
    client asks for most often.
    """
    if query.limit == UNLIMITED:
        return query.start + returned

    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    return total or 0


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of results, with the totals the response headers need."""

    objects: list[T]
    total: int
    library_version: int


def _field_sort(name: str) -> ColumnElement[Any]:
    """Return a sort expression for a field kept in ``item_fields``."""
    return (
        select(ItemField.value)
        .where(ItemField.item_id == Item.id, ItemField.field == name)
        .scalar_subquery()
    )


def _apply_sort(statement: Select[Any], query: ListQuery) -> Select[Any]:
    column = _COLUMN_SORTS.get(query.sort)
    if column is None:
        # Everything else names an ordinary field, e.g. publisher or language.
        # `addedBy` is only meaningful in group libraries and is not tracked
        # yet, so it falls through to an empty sort key rather than failing.
        column = _field_sort(query.sort)

    ordering = column.desc() if query.direction is Direction.DESCENDING else column.asc()
    # Key order alone is not a total order, so the item key breaks ties and
    # keeps pagination stable across requests.
    return statement.order_by(ordering, Item.key.asc())


def _expression_filter(
    expressions: Sequence[SearchExpression],
    build: Any,
) -> list[ColumnElement[bool]]:
    """Turn parsed search expressions into predicates.

    Alternatives within one expression are OR-ed and the negation, if any,
    applies to that whole group. Separate expressions are AND-ed by being
    returned as separate clauses.
    """
    clauses: list[ColumnElement[bool]] = []
    for expression in expressions:
        matched = or_(*(build(value) for value in expression.values))
        clauses.append(not_(matched) if expression.negated else matched)
    return clauses


def _has_tag(library_id: int) -> Any:
    def build(name: str) -> ColumnElement[bool]:
        return (
            select(ItemTag.item_id)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(
                ItemTag.item_id == Item.id,
                Tag.library_id == library_id,
                Tag.name == name,
            )
            .exists()
        )

    return build


def _quick_search(query: ListQuery) -> ColumnElement[bool]:
    """Return the predicate for the ``q`` parameter.

    ``LIKE`` is used rather than a full-text index so the same query works on
    SQLite and PostgreSQL; a dialect-specific backend can replace this without
    the callers noticing.
    """
    pattern = f"%{query.q}%"

    if query.qmode == QuickSearchMode.EVERYTHING:
        in_any_field = (
            select(ItemField.item_id)
            .where(ItemField.item_id == Item.id, ItemField.value.ilike(pattern))
            .exists()
        )
        return or_(in_any_field, *(column.ilike(pattern) for column in _QUICK_SEARCH_COLUMNS))

    return or_(*(column.ilike(pattern) for column in _QUICK_SEARCH_COLUMNS))


async def _scope_filters(
    session: AsyncSession,
    library: Library,
    scope: Scope,
    key: str | None,
) -> list[ColumnElement[bool]]:
    """Return the predicates that restrict a listing to ``scope``."""
    if scope is Scope.TRASH:
        return [Item.deleted.is_(True)]

    if scope is Scope.TOP:
        return [Item.parent_id.is_(None)]

    if scope in (Scope.PUBLICATIONS, Scope.PUBLICATIONS_TOP):
        published: list[ColumnElement[bool]] = [Item.in_publications.is_(True)]
        if scope is Scope.PUBLICATIONS_TOP:
            published.append(Item.parent_id.is_(None))
        return published

    if scope is Scope.CHILDREN:
        parent = await get_item(session, library, key or "")
        return [Item.parent_id == parent.id]

    if scope in (Scope.COLLECTION, Scope.COLLECTION_TOP):
        collection = await session.scalar(
            select(Collection).where(Collection.library_id == library.id, Collection.key == key)
        )
        if collection is None:
            raise NotFoundError("Collection not found")

        member = (
            select(CollectionItem.item_id)
            .where(
                CollectionItem.collection_id == collection.id,
                CollectionItem.item_id == Item.id,
            )
            .exists()
        )
        filters: list[ColumnElement[bool]] = [member]
        if scope is Scope.COLLECTION_TOP:
            filters.append(Item.parent_id.is_(None))
        return filters

    return []


async def build_item_query(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    scope: Scope = Scope.ALL,
    key: str | None = None,
) -> Select[Any]:
    """Return the ``SELECT`` matching ``query`` within ``scope``, unordered."""
    filters: list[ColumnElement[bool]] = [Item.library_id == library.id]
    filters += await _scope_filters(session, library, scope, key)

    # The trash is excluded everywhere except in the trash itself.
    if scope is not Scope.TRASH and not query.include_trashed:
        filters.append(Item.deleted.is_(False))

    if query.item_keys:
        filters.append(Item.key.in_(query.item_keys))

    if query.since:
        filters.append(Item.version > query.since)

    for expression in query.item_types:
        for value in expression.values:
            if not get_schema().is_valid_item_type(value):
                raise InvalidInputError(f"Invalid itemType '{value}'")
    filters += _expression_filter(query.item_types, lambda value: Item.item_type == value)
    filters += _expression_filter(query.tags, _has_tag(library.id))

    if query.q:
        filters.append(_quick_search(query))

    return select(Item).where(and_(*filters))


async def item_ids_in_scope(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    scope: Scope = Scope.ALL,
    key: str | None = None,
) -> Select[Any]:
    """Return a ``SELECT`` of the item ids matching ``scope``.

    The tag endpoints count tags against a set of items, so they reuse the same
    filtering the item endpoints do rather than repeating it.
    """
    statement = await build_item_query(session, library, query, scope, key)
    return statement.with_only_columns(Item.id)


async def list_items(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    scope: Scope = Scope.ALL,
    key: str | None = None,
) -> Page[Item]:
    """Return one page of items, together with the total number of matches."""
    statement = await build_item_query(session, library, query, scope, key)

    result = await session.scalars(paginate(_apply_sort(statement, query), query))
    objects = list(result)

    return Page(
        objects=objects,
        total=await count_matches(session, statement, query, len(objects)),
        library_version=library.version,
    )


async def get_item(session: AsyncSession, library: Library, key: str) -> Item:
    """Return one item by key."""
    item = await session.scalar(select(Item).where(Item.library_id == library.id, Item.key == key))
    if item is None:
        raise NotFoundError("Item does not exist")
    return item


async def count_children(session: AsyncSession, items: Sequence[Item]) -> dict[int, int]:
    """Return how many non-trashed children each of ``items`` has, by item id.

    Items with no children are absent from the mapping, so callers read it with
    a default of zero.
    """
    if not items:
        return {}

    result = await session.execute(
        select(Item.parent_id, func.count())
        .where(Item.parent_id.in_([item.id for item in items]), Item.deleted.is_(False))
        .group_by(Item.parent_id)
    )
    return {parent_id: count for parent_id, count in result.all()}


async def collection_keys_for(session: AsyncSession, items: Sequence[Item]) -> dict[int, list[str]]:
    """Return the keys of the collections each of ``items`` belongs to, by item id."""
    if not items:
        return {}

    result = await session.execute(
        select(CollectionItem.item_id, Collection.key)
        .join(Collection, Collection.id == CollectionItem.collection_id)
        .where(CollectionItem.item_id.in_([item.id for item in items]))
        .order_by(Collection.key)
    )

    keys: dict[int, list[str]] = {}
    for item_id, key in result.all():
        keys.setdefault(item_id, []).append(key)
    return keys


async def tags_for(
    session: AsyncSession, items: Sequence[Item]
) -> dict[int, list[tuple[str, int]]]:
    """Return the ``(name, type)`` pairs attached to each of ``items``, by item id."""
    if not items:
        return {}

    result = await session.execute(
        select(ItemTag.item_id, Tag.name, Tag.type)
        .join(Tag, Tag.id == ItemTag.tag_id)
        .where(ItemTag.item_id.in_([item.id for item in items]))
        .order_by(Tag.name)
    )

    tags: dict[int, list[tuple[str, int]]] = {}
    for item_id, name, type_ in result.all():
        tags.setdefault(item_id, []).append((name, type_))
    return tags


async def parent_keys_for(session: AsyncSession, items: Sequence[Item]) -> dict[int, str]:
    """Return the key of every parent named by ``items``, by parent id.

    Only the items that have a parent contribute, so a page of top-level items
    costs no query at all.
    """
    parent_ids = {item.parent_id for item in items if item.parent_id is not None}
    if not parent_ids:
        return {}

    result = await session.execute(select(Item.id, Item.key).where(Item.id.in_(parent_ids)))
    return {item_id: key for item_id, key in result.all()}
