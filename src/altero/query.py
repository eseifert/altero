"""The query parameters shared by the listing endpoints.

Parsing lives here rather than in the API layer so the rules are testable
without a request, and so a different HTTP layer only has to hand over strings.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from altero.errors import InvalidInputError
from altero.pagination import DEFAULT_LIMIT, MAX_LIMIT, UNLIMITED, clamp_limit
from altero.search import SearchExpression, parse_expressions


class Format(StrEnum):
    """Response formats supported for listing endpoints."""

    JSON = "json"
    KEYS = "keys"
    VERSIONS = "versions"


class QuickSearchMode(StrEnum):
    """Interpretation of the ``q`` parameter."""

    TITLE_CREATOR_YEAR = "titleCreatorYear"
    EVERYTHING = "everything"


class TagSearchMode(StrEnum):
    """Interpretation of the ``q`` parameter on tag endpoints."""

    CONTAINS = "contains"
    STARTS_WITH = "startsWith"


class Direction(StrEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"


#: Sort fields accepted by the item endpoints.
ITEM_SORT_FIELDS = frozenset(
    {
        "dateAdded",
        "dateModified",
        "title",
        "creator",
        "itemType",
        "date",
        "publisher",
        "publicationTitle",
        "journalAbbreviation",
        "language",
        "accessDate",
        "libraryCatalog",
        "callNumber",
        "rights",
        "extra",
        "addedBy",
        "serverDateModified",
    }
)

#: Sort fields accepted by the collection and saved search endpoints.
NAMED_SORT_FIELDS = frozenset({"dateAdded", "dateModified", "title", "name"})

#: Sort fields accepted by the tag endpoints.
TAG_SORT_FIELDS = frozenset({"title", "numItems"})


@dataclass(frozen=True, slots=True)
class ListQuery:
    """A parsed listing request."""

    response_format: Format = Format.JSON
    include: frozenset[str] = frozenset({"data"})
    item_keys: tuple[str, ...] = ()
    item_types: tuple[SearchExpression, ...] = ()
    tags: tuple[SearchExpression, ...] = ()
    q: str | None = None
    #: Interpretation of ``q``. Item endpoints accept the
    #: :class:`QuickSearchMode` values, tag endpoints the :class:`TagSearchMode`
    #: ones, so this is kept as the validated string.
    qmode: str = QuickSearchMode.TITLE_CREATOR_YEAR
    since: int = 0
    sort: str = "dateModified"
    direction: Direction = Direction.DESCENDING
    limit: int = DEFAULT_LIMIT
    start: int = 0
    include_trashed: bool = False
    #: Raw query parameters, kept so pagination links can reproduce them.
    raw: tuple[tuple[str, str], ...] = field(default=())


#: Largest number of keys accepted in a single ``itemKey`` parameter.
MAX_KEYS = 50


def _parse_enum[T: StrEnum](enum: type[T], value: str | None, default: T, name: str) -> T:
    if value is None:
        return default
    try:
        return enum(value)
    except ValueError:
        raise InvalidInputError(f"Invalid '{name}' value '{value}'") from None


def _parse_int[T: int | None](value: str | None, default: T, name: str) -> int | T:
    """Return ``value`` as an integer, or ``default`` if it is not one.

    Upstream answers 200 for `limit=abc` rather than rejecting it, so an
    unreadable number is ignored instead of failing the request.
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_qmode(value: str | None, *, tag_endpoint: bool) -> str:
    """Return the validated ``qmode``.

    The reference implementation compares lowercased, so ``startsWith`` and
    ``startswith`` are both accepted. The canonical spelling is returned.
    """
    modes: tuple[str, ...] = (
        (TagSearchMode.CONTAINS, TagSearchMode.STARTS_WITH)
        if tag_endpoint
        else (QuickSearchMode.TITLE_CREATOR_YEAR, QuickSearchMode.EVERYTHING)
    )
    if value is None or value == "":
        return modes[0]

    for mode in modes:
        if value.lower() == mode.lower():
            return str(mode)
    raise InvalidInputError(f"Invalid 'qmode' value '{value}'")


def default_direction(sort: str) -> Direction:
    """Return the direction used when the client does not name one.

    Any sort field whose name begins with ``date`` counts down, which is the
    rule the reference implementation applies.
    """
    return Direction.DESCENDING if sort.startswith("date") else Direction.ASCENDING


def limit_maximum(response_format: Format) -> int:
    """Return the largest page size allowed for ``response_format``."""
    if response_format in (Format.KEYS, Format.VERSIONS):
        return UNLIMITED
    return MAX_LIMIT


def default_limit(response_format: Format) -> int:
    """Return the page size used when the client asks for none.

    ``keys`` and ``versions`` are unpaginated by default: clients use them to
    discover everything that changed, so truncating them to 25 would silently
    break syncing.
    """
    if response_format in (Format.KEYS, Format.VERSIONS):
        return UNLIMITED
    return DEFAULT_LIMIT


def parse_list_query(
    params: list[tuple[str, str]],
    *,
    sort_fields: frozenset[str],
    default_sort: str = "dateModified",
    tag_endpoint: bool = False,
) -> ListQuery:
    """Build a :class:`ListQuery` from a request's query parameters.

    ``params`` is the full list of pairs rather than a mapping, because ``tag``
    may legitimately appear more than once.

    Args:
        sort_fields: Sort fields this endpoint accepts.
        default_sort: Sort applied when the client names none.
        tag_endpoint: Whether ``qmode`` should be read as a tag search mode
            rather than an item quick-search mode.
    """
    single = {name: value for name, value in params}
    repeated = [value for name, value in params if name == "tag"]

    if len([name for name, _ in params if name == "itemType"]) > 1:
        raise InvalidInputError("Cannot specify 'itemType' more than once")

    response_format = _parse_enum(Format, single.get("format"), Format.JSON, "format")

    # A direction supplied as `sort` is moved across and the default sort kept,
    # which is what the reference implementation does.
    sort = single.get("sort") or default_sort
    direction_override = single.get("direction")
    if sort in (Direction.ASCENDING, Direction.DESCENDING):
        direction_override = sort
        sort = default_sort
    if sort not in sort_fields:
        raise InvalidInputError(f"Invalid 'sort' value '{sort}'")

    direction = _parse_enum(Direction, direction_override, default_direction(sort), "direction")

    item_keys = tuple(key for key in (single.get("itemKey") or "").split(",") if key)
    if len(item_keys) > MAX_KEYS:
        raise InvalidInputError(f"Cannot request more than {MAX_KEYS} items at a time")

    return ListQuery(
        response_format=response_format,
        include=frozenset((single.get("include") or "data").split(",")),
        item_keys=item_keys,
        item_types=parse_expressions([single["itemType"]] if "itemType" in single else []),
        tags=parse_expressions(repeated),
        q=single.get("q") or None,
        qmode=_parse_qmode(single.get("qmode"), tag_endpoint=tag_endpoint),
        since=_parse_int(single.get("since"), 0, "since"),
        sort=sort,
        direction=direction,
        limit=clamp_limit(
            _parse_int(single.get("limit"), None, "limit"),
            maximum=limit_maximum(response_format),
            default=default_limit(response_format),
        ),
        start=max(0, _parse_int(single.get("start"), 0, "start")),
        include_trashed=single.get("includeTrashed") == "1",
        raw=tuple(params),
    )
