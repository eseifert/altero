"""Reading items out of a library."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum, auto
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, distinct, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from altero.errors import InvalidInputError, NotFoundError
from altero.itemschema import get_schema
from altero.models import (
    Collection,
    CollectionItem,
    FullText,
    Item,
    ItemField,
    ItemTag,
    Library,
    Tag,
    User,
)
from altero.pagination import UNLIMITED
from altero.query import Direction, ListQuery, QuickSearchMode
from altero.search import SearchExpression, parse_search_string
from altero.services import duplicates

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
    #: A collection together with everything nested inside it. Not in the v3
    #: API, which scopes to one collection exactly; it is the desktop client's
    #: "Show Items from Subcollections", and here it is what a shared collection
    #: link means -- somebody sharing a branch means the branch.
    COLLECTION_TREE = auto()
    COLLECTION_TREE_TOP = auto()
    #: The owner's My Publications, which is a public view of one library.
    PUBLICATIONS = auto()
    PUBLICATIONS_TOP = auto()
    #: The three views the desktop client offers beside the collections. None
    #: of them is in the v3 API: the client works each one out in the copy of
    #: the library it holds, so altero has to answer them from the library
    #: itself. See `docs/compatibility.md`.
    UNFILED = auto()
    DUPLICATES = auto()
    RECENTLY_READ = auto()


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


#: Sorts that order by a person rather than by a value on the item, with the
#: column each reads. ``editedBy`` is not upstream's; see the authorship section
#: of ``docs/compatibility.md``.
_AUTHOR_SORTS: dict[str, InstrumentedAttribute[int | None]] = {
    "addedBy": Item.created_by_user_id,
    "editedBy": Item.last_modified_by_user_id,
}


def _author_name_sort(column: InstrumentedAttribute[int | None]) -> ColumnElement[Any]:
    """Return a sort expression for the name behind ``column``.

    The name is the display name or the username, which is what
    ``Zotero_Users::getName`` returns and therefore what upstream sorts on --
    not the username alone, and not the id.
    """
    return (
        select(func.coalesce(func.nullif(User.display_name, ""), User.username))
        .where(User.id == column)
        .scalar_subquery()
    )


def _apply_sort(statement: Select[Any], query: ListQuery, *, by_author: bool = True) -> Select[Any]:
    """Order a listing.

    Args:
        by_author: Whether ``addedBy`` and ``editedBy`` have anything to sort
            by. When they do not -- a personal library, or a group whose items
            all predate authorship being recorded -- upstream quietly sorts by
            ``dateAdded`` instead, which is what ``False`` produces.
    """
    author_column = _AUTHOR_SORTS.get(query.sort)
    if author_column is not None:
        column = _author_name_sort(author_column) if by_author else Item.date_added
    elif (mapped := _COLUMN_SORTS.get(query.sort)) is not None:
        column = mapped
    else:
        # Everything else names an ordinary field, e.g. publisher or language.
        column = _field_sort(query.sort)

    ordering = column.desc() if query.direction is Direction.DESCENDING else column.asc()
    # Key order alone is not a total order, so the item key breaks ties and
    # keeps pagination stable across requests.
    return statement.order_by(ordering, Item.key.asc())


async def _has_authorship(session: AsyncSession, library: Library, sort: str) -> bool:
    """Whether anything in ``library`` records the author ``sort`` reads.

    Asked once per request rather than assumed, because upstream's fallback
    depends on the answer: it runs the same check with a `SELECT DISTINCT
    createdByUserID` before deciding what to order by.
    """
    column = _AUTHOR_SORTS.get(sort)
    if column is None:
        return False

    found = await session.scalar(
        select(Item.id).where(Item.library_id == library.id, column.is_not(None)).limit(1)
    )
    return found is not None


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

    The query is split into parts, each of which must match something: upstream
    emits one `AND (...)` per part and ORs the fields together inside it, so
    ``q=quantum computing`` wants both words and not the phrase.

    ``LIKE`` is used rather than a full-text index so the same query works on
    SQLite and PostgreSQL; a dialect-specific backend can replace this without
    the callers noticing.
    """
    clauses: list[ColumnElement[bool]] = []
    for part in parse_search_string(query.q or ""):
        pattern = f"%{part}%"
        alternatives: list[ColumnElement[bool]] = [
            column.ilike(pattern) for column in _QUICK_SEARCH_COLUMNS
        ]

        if query.qmode == QuickSearchMode.EVERYTHING:
            alternatives.append(
                select(ItemField.item_id)
                .where(ItemField.item_id == Item.id, ItemField.value.ilike(pattern))
                .exists()
            )
            alternatives.append(
                select(FullText.item_id)
                .where(FullText.item_id == Item.id, FullText.content.ilike(pattern))
                .exists()
            )

        clauses.append(or_(*alternatives))

    # Every part can drop out -- `q=0` is upstream's case -- and a search with
    # nothing left to ask for restricts nothing.
    return and_(*clauses) if clauses else true()


async def _scope_filters(
    session: AsyncSession,
    library: Library,
    scope: Scope,
    key: str | None,
    to_parents: bool,
) -> list[ColumnElement[bool]]:
    """Return the predicates that restrict a listing to ``scope``.

    ``to_parents`` says the caller will map matches onto their top-level items
    afterwards, so a ``/top`` scope must not exclude child items here: they are
    how their parents are found.
    """
    if scope is Scope.TRASH:
        return [Item.deleted.is_(True)]

    if scope is Scope.TOP:
        return [] if to_parents else [Item.parent_id.is_(None)]

    if scope in (Scope.PUBLICATIONS, Scope.PUBLICATIONS_TOP):
        published: list[ColumnElement[bool]] = [Item.in_publications.is_(True)]
        if scope is Scope.PUBLICATIONS_TOP and not to_parents:
            published.append(Item.parent_id.is_(None))
        return published

    if scope is Scope.CHILDREN:
        parent = await get_item(session, library, key or "")
        return [Item.parent_id == parent.id]

    if scope is Scope.UNFILED:
        # Filed nowhere: exactly what the client's Unfiled Items shows, and the
        # only one of the three that is a plain question about the rows.
        filed = select(CollectionItem.item_id).where(CollectionItem.item_id == Item.id).exists()
        unfiled: list[ColumnElement[bool]] = [~filed, Item.deleted.is_(False)]
        if not to_parents:
            unfiled.append(Item.parent_id.is_(None))
        return unfiled

    if scope is Scope.DUPLICATES:
        found = await duplicates.duplicate_item_ids(session, library)
        # `in_(())` is a valid empty predicate, so a library with no duplicates
        # answers with an empty page rather than with everything.
        return [Item.id.in_(found)]

    if scope is Scope.RECENTLY_READ:
        return [Item.id.in_(await _recently_read_ids(session, library))]

    if scope in (
        Scope.COLLECTION,
        Scope.COLLECTION_TOP,
        Scope.COLLECTION_TREE,
        Scope.COLLECTION_TREE_TOP,
    ):
        collection = await session.scalar(
            select(Collection).where(Collection.library_id == library.id, Collection.key == key)
        )
        if collection is None:
            raise NotFoundError("Collection not found")

        recursive = scope in (Scope.COLLECTION_TREE, Scope.COLLECTION_TREE_TOP)
        if recursive:
            from altero.services.collections import subtree

            ids = [entry.id for entry in await subtree(session, collection)]
        else:
            ids = [collection.id]

        member = (
            select(CollectionItem.item_id)
            .where(
                CollectionItem.collection_id.in_(ids),
                CollectionItem.item_id == Item.id,
            )
            .exists()
        )
        filters: list[ColumnElement[bool]] = [member]
        if scope in (Scope.COLLECTION_TOP, Scope.COLLECTION_TREE_TOP) and not to_parents:
            filters.append(Item.parent_id.is_(None))
        return filters

    return []


#: How far back "recently" reaches. A guess: the client keeps this view as a
#: saved search whose terms altero cannot see, and a window is the reading of it
#: that cannot quietly grow into "everything ever opened". Recorded as a guess
#: in `docs/compatibility.md`.
RECENTLY_READ_DAYS = 90


async def _recently_read_ids(session: AsyncSession, library: Library) -> set[int]:
    """Return the items whose attachments were read in the last three months.

    Read off `lastRead`, which Zotero 7 writes onto an attachment when its
    reader is closed and syncs like any other field. The item that comes back
    is the one the sidebar lists -- an attachment's parent where it has one,
    and the attachment itself where it is top-level.
    """
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=RECENTLY_READ_DAYS)
    cutoff = since.timestamp()

    rows = await session.execute(
        select(Item.id, Item.parent_id, ItemField.value)
        .join(ItemField, ItemField.item_id == Item.id)
        .where(
            Item.library_id == library.id,
            Item.deleted.is_(False),
            ItemField.field == "lastRead",
        )
    )

    read: set[int] = set()
    for item_id, parent_id, value in rows.all():
        try:
            # Seconds since the epoch, as the client writes it. Anything else
            # is a field altero did not write and does not have to understand.
            when = float(value)
        except TypeError, ValueError:
            continue
        if when >= cutoff:
            read.add(parent_id or item_id)
    return read


#: Scopes that answer with top-level items, and so have parents to map onto.
_TOP_SCOPES = frozenset(
    {
        Scope.TOP,
        Scope.COLLECTION_TOP,
        Scope.COLLECTION_TREE_TOP,
        Scope.PUBLICATIONS_TOP,
        Scope.UNFILED,
        Scope.DUPLICATES,
        Scope.RECENTLY_READ,
    }
)


def _matches_child_items(query: ListQuery) -> bool:
    """Whether ``query`` can be satisfied by a child item.

    These are the four parameters upstream keeps its parent-items table for. A
    quick search reaches an attachment's full text and a child note's title, a
    tag or a key may name a child, and `itemType=annotation` asks for children
    only -- so in a ``/top`` listing each of them describes a parent indirectly.

    `since` is deliberately absent, as it is upstream: it is what a syncing
    client sends, and answering it with parents would report objects whose own
    version had not moved.
    """
    return bool(query.q or query.tags or query.item_keys or query.item_types)


async def build_item_query(
    session: AsyncSession,
    library: Library,
    query: ListQuery,
    scope: Scope = Scope.ALL,
    key: str | None = None,
) -> Select[Any]:
    """Return the ``SELECT`` matching ``query`` within ``scope``, unordered."""
    to_parents = scope in _TOP_SCOPES and _matches_child_items(query)

    filters: list[ColumnElement[bool]] = [Item.library_id == library.id]
    filters += await _scope_filters(session, library, scope, key, to_parents)

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

    if not to_parents:
        return select(Item).where(and_(*filters))

    # A child matched, so answer with the item it hangs under. An annotation
    # hangs under an attachment which hangs under the item, and that is as deep
    # as Zotero goes, so one join reaches the top from anywhere.
    parent = aliased(Item)
    top_level_id = func.coalesce(parent.parent_id, Item.parent_id, Item.id)
    matched = (
        select(distinct(top_level_id))
        .select_from(Item)
        .outerjoin(parent, parent.id == Item.parent_id)
        .where(and_(*filters))
    )

    statement = select(Item).where(Item.id.in_(matched))
    if not query.include_trashed:
        # The match itself was untrashed, but its parent may not be, and a
        # listing that is not the trash should not surface it.
        statement = statement.where(Item.deleted.is_(False))
    return statement


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

    by_author = await _has_authorship(session, library, query.sort)
    result = await session.scalars(
        paginate(_apply_sort(statement, query, by_author=by_author), query)
    )
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


async def authors_for(session: AsyncSession, items: Sequence[Item]) -> dict[int, User]:
    """Return the accounts ``items`` name as their author, by user id.

    One query for a whole page rather than two per item. An id with no account
    behind it simply does not appear: somebody may have left, and the
    serialiser renders nothing for a name it cannot resolve, which is what
    upstream does when its own lookup fails.
    """
    wanted = {
        user_id
        for item in items
        for user_id in (item.created_by_user_id, item.last_modified_by_user_id)
        if user_id is not None
    }
    if not wanted:
        return {}

    found = await session.scalars(select(User).where(User.id.in_(wanted)))
    return {user.id: user for user in found}


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
