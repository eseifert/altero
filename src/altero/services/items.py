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


def paginate(statement: Select[Any], query: ListQuery) -> Select[Any]:
    """Apply ``start`` and ``limit``, omitting LIMIT when the page is unlimited.

    ``format=keys`` and ``format=versions`` default to unlimited, so the whole
    result set comes back in one response.
    """
    statement = statement.offset(query.start) if query.start else statement
    return statement if query.limit == UNLIMITED else statement.limit(query.limit)


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

    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    result = await session.scalars(paginate(_apply_sort(statement, query), query))

    return Page(objects=list(result), total=total or 0, library_version=library.version)


async def get_item(session: AsyncSession, library: Library, key: str) -> Item:
    """Return one item by key."""
    item = await session.scalar(select(Item).where(Item.library_id == library.id, Item.key == key))
    if item is None:
        raise NotFoundError("Item does not exist")
    return item


async def count_children(session: AsyncSession, item: Item) -> int:
    """Return how many non-trashed children ``item`` has."""
    total = await session.scalar(
        select(func.count())
        .select_from(Item)
        .where(Item.parent_id == item.id, Item.deleted.is_(False))
    )
    return total or 0


async def collection_keys_for(session: AsyncSession, item: Item) -> list[str]:
    """Return the keys of the collections ``item`` belongs to."""
    result = await session.scalars(
        select(Collection.key)
        .join(CollectionItem, CollectionItem.collection_id == Collection.id)
        .where(CollectionItem.item_id == item.id)
        .order_by(Collection.key)
    )
    return list(result)


async def tags_for(session: AsyncSession, item: Item) -> list[tuple[str, int]]:
    """Return ``(name, type)`` for each tag attached to ``item``."""
    result = await session.execute(
        select(Tag.name, Tag.type)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .where(ItemTag.item_id == item.id)
        .order_by(Tag.name)
    )
    return [(name, type_) for name, type_ in result.all()]
