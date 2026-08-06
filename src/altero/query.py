"""The query parameters shared by the listing endpoints.

Parsing lives here rather than in the API layer so the rules are testable
without a request, and so a different HTTP layer only has to hand over strings.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from altero.atom import (
    CONTENT_INCLUDES,
    ITEM_CONTENT_VALUES,
    NAMED_CONTENT_VALUES,
    TAG_CONTENT_VALUES,
    parse_content,
)
from altero.cite.styles import DEFAULT_LOCALE, DEFAULT_STYLE
from altero.errors import InvalidInputError
from altero.pagination import DEFAULT_LIMIT, MAX_LIMIT, UNLIMITED, clamp_limit
from altero.search import SearchExpression, parse_expressions


class Format(StrEnum):
    """Response formats supported for listing endpoints."""

    JSON = "json"
    ATOM = "atom"
    KEYS = "keys"
    VERSIONS = "versions"
    CSLJSON = "csljson"
    BIB = "bib"
    BIBTEX = "bibtex"
    BIBLATEX = "biblatex"
    RIS = "ris"


#: Formats written from an item rather than describing one: a file to hand to
#: another program. Upstream produces these through a translation server and
#: offers more of them; these three are the ones altero writes.
EXPORT_FORMATS = frozenset({Format.BIBTEX, Format.BIBLATEX, Format.RIS})

#: Formats the item endpoints answer in.
ITEM_FORMATS = frozenset(Format)

#: Formats every other listing endpoint answers in. Collections, searches and
#: tags have no citation form: upstream rejects `format=bib` on them rather than
#: ignoring it, and a client that asked would otherwise get JSON it did not ask
#: for.
OBJECT_FORMATS = frozenset({Format.JSON, Format.ATOM, Format.KEYS, Format.VERSIONS})

#: Formats a request for one object may ask for. `keys` and `versions` describe
#: a set and say nothing useful about a single object.
SINGLE_OBJECT_FORMATS = (
    frozenset({Format.JSON, Format.ATOM, Format.CSLJSON, Format.BIB}) | EXPORT_FORMATS
)

#: Formats that answer with an Atom entry rather than a JSON envelope for a
#: single object. Collections, searches and tags have no citation form, so this
#: is the only non-JSON format they serve one object in.
SINGLE_NAMED_FORMATS = frozenset({Format.JSON, Format.ATOM})

#: Values `include` accepts. `data` is the item itself; the rest are rendered
#: from it. Upstream also accepts `html`, which is Atom's own and is asked for
#: through `content` instead -- see :mod:`altero.atom`.
INCLUDE_VALUES = frozenset({"data", "bib", "citation", "csljson", "none"}) | {
    str(name) for name in EXPORT_FORMATS
}

#: Parameters that describe a page of results and so cannot apply to a
#: bibliography, which is one rendered document.
_PAGING_PARAMS = ("sort", "direction", "start", "limit", "order")


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
        # Not upstream's. `dataserver#153` asks for a way to sort a group
        # library by who last touched each item and has been open since 2023;
        # altero records that anyway for `meta.lastModifiedByUser`, so the sort
        # costs nothing beyond accepting the name. Recorded as a divergence in
        # `docs/compatibility.md`.
        "editedBy",
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
    #: What ``format=atom`` puts in each entry's ``content``, in the order the
    #: entry emits it. Empty for every other format.
    content: tuple[str, ...] = ()
    item_keys: tuple[str, ...] = ()
    #: The same for a collection or a saved search listing. Each object type
    #: names its own parameter and reads only that one, as upstream does.
    collection_keys: tuple[str, ...] = ()
    search_keys: tuple[str, ...] = ()
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
    #: Citation style, locale and link handling, used by the rendered formats.
    style: str = DEFAULT_STYLE
    locale: str = DEFAULT_LOCALE
    linkwrap: bool = False
    #: Raw query parameters, kept so pagination links can reproduce them.
    raw: tuple[tuple[str, str], ...] = field(default=())


#: The page size a request naming explicit object keys is given, whatever it
#: asked for -- `Zotero_API::MAX_OBJECT_KEYS`, assigned as
#: ``$finalParams['limit']`` the moment ``itemKey``, ``collectionKey`` or
#: ``searchKey`` is seen. It is not a cap on how many keys may be named:
#: upstream never counts them, it filters out the malformed ones and pages the
#: rest. The number matters because it is also the client's own batch size
#: (``Zotero.Sync.APIClient.MAX_OBJECTS_PER_REQUEST``), so a client asking for
#: a hundred objects by name is answered with a hundred rather than a page.
MAX_OBJECT_KEYS = 100

#: Entries a single bibliography may hold. It is both the maximum and the
#: default page size for ``format=bib``: a bibliography is one document, so a
#: client asking for one is not paging through anything.
MAX_BIBLIOGRAPHY_ITEMS = 150


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
    if response_format is Format.BIB:
        return MAX_BIBLIOGRAPHY_ITEMS
    return MAX_LIMIT


def default_limit(response_format: Format) -> int:
    """Return the page size used when the client asks for none.

    ``keys`` and ``versions`` are unpaginated by default: clients use them to
    discover everything that changed, so truncating them to 25 would silently
    break syncing.
    """
    if response_format in (Format.KEYS, Format.VERSIONS):
        return UNLIMITED
    if response_format is Format.BIB:
        return MAX_BIBLIOGRAPHY_ITEMS
    return DEFAULT_LIMIT


def _includes_for_content(content: tuple[str, ...]) -> frozenset[str]:
    """Return the ``include`` set an Atom ``content`` needs rendered.

    ``data`` is always in it, whatever was asked for: an entry's title, item
    type and creator summary come from the item's own properties, so the
    envelope has to carry them even when the body is a bibliography or nothing
    at all.
    """
    named = {CONTENT_INCLUDES[value] for value in content}
    return frozenset({"data"}) | {value for value in named if value is not None}


def _parse_include(value: str | None, response_format: Format) -> frozenset[str]:
    """Return the validated ``include`` set.

    Only ``format=json`` carries anything to include in, so asking for it
    elsewhere is rejected rather than ignored: a client that asked for a
    citation and received plain data would have no way to tell. Atom asks the
    same question through ``content``.
    """
    if value is None:
        return frozenset({"data"})

    if response_format is not Format.JSON:
        raise InvalidInputError("'include' is valid only for format=json")

    values = frozenset(part for part in value.split(",") if part)
    for part in sorted(values):
        if part not in INCLUDE_VALUES:
            raise InvalidInputError(f"Invalid 'include' value '{part}'")
    if "none" in values and len(values) > 1:
        raise InvalidInputError("include=none is not valid in multi-format responses")
    return values or frozenset({"data"})


def parse_list_query(
    params: list[tuple[str, str]],
    *,
    sort_fields: frozenset[str],
    default_sort: str = "dateModified",
    tag_endpoint: bool = False,
    formats: frozenset[Format] = OBJECT_FORMATS,
    content_values: frozenset[str] | None = None,
) -> ListQuery:
    """Build a :class:`ListQuery` from a request's query parameters.

    ``params`` is the full list of pairs rather than a mapping, because ``tag``
    may legitimately appear more than once.

    Args:
        sort_fields: Sort fields this endpoint accepts.
        default_sort: Sort applied when the client names none.
        tag_endpoint: Whether ``qmode`` should be read as a tag search mode
            rather than an item quick-search mode.
        formats: Response formats this endpoint can produce.
        content_values: Atom ``content`` values this endpoint can render.
            Defaults to the item set when every format is on offer and to the
            reduced one otherwise.
    """
    if content_values is None:
        # An endpoint that can render a bibliography is an item endpoint, and
        # only those have every content value to offer.
        content_values = (
            ITEM_CONTENT_VALUES
            if Format.BIB in formats
            else TAG_CONTENT_VALUES
            if tag_endpoint
            else NAMED_CONTENT_VALUES
        )
    single = {name: value for name, value in params}
    repeated = [value for name, value in params if name == "tag"]

    if len([name for name, _ in params if name == "itemType"]) > 1:
        raise InvalidInputError("Cannot specify 'itemType' more than once")

    response_format = _parse_enum(Format, single.get("format"), Format.JSON, "format")
    if response_format not in formats:
        raise InvalidInputError(f"Invalid 'format' value '{response_format}'")

    if response_format is Format.BIB:
        for name in _PAGING_PARAMS:
            if name in single:
                raise InvalidInputError(f"'{name}' is not valid for format=bib")

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

    # Leading, trailing and doubled commas are all tolerated, which is
    # `trim($value, ",")` followed by upstream's filter. Nothing counts them:
    # a client that names more objects than a page holds is paged, not refused.
    item_keys = tuple(key for key in (single.get("itemKey") or "").split(",") if key)
    collection_keys = tuple(key for key in (single.get("collectionKey") or "").split(",") if key)
    search_keys = tuple(key for key in (single.get("searchKey") or "").split(",") if key)

    # `content` is Atom's `include`, and is refused elsewhere for the reason
    # `include` is refused outside JSON: a client that asked for a citation and
    # got something else back has no way to notice.
    if response_format is Format.ATOM:
        content = parse_content(single.get("content"), content_values)
        include = _includes_for_content(content)
    else:
        content = ()
        include = _parse_include(single.get("include"), response_format)
        if "content" in single:
            raise InvalidInputError("'content' is valid only for format=atom")

    limit = clamp_limit(
        _parse_int(single.get("limit"), None, "limit"),
        maximum=limit_maximum(response_format),
        default=default_limit(response_format),
    )
    # Naming objects sets the page size, over whatever was asked for: upstream
    # assigns it inside the parameter's own case, so it is the last word. What
    # a client that named a hundred keys wants is those hundred, not the first
    # page of them -- and it is the sync's download step that does this, so a
    # short answer there is a library that never finishes coming down.
    #
    # The unpaginated formats keep their own rule. `keys` and `versions` answer
    # with everything by design, and holding them to a hundred would turn a
    # complete answer into a truncated one.
    if (item_keys or collection_keys or search_keys) and limit != UNLIMITED:
        limit = MAX_OBJECT_KEYS

    return ListQuery(
        response_format=response_format,
        include=include,
        content=content,
        item_keys=item_keys,
        collection_keys=collection_keys,
        search_keys=search_keys,
        item_types=parse_expressions([single["itemType"]] if "itemType" in single else []),
        tags=parse_expressions(repeated),
        q=single.get("q") or None,
        qmode=_parse_qmode(single.get("qmode"), tag_endpoint=tag_endpoint),
        since=_parse_int(single.get("since"), 0, "since"),
        sort=sort,
        direction=direction,
        limit=limit,
        start=max(0, _parse_int(single.get("start"), 0, "start")),
        include_trashed=single.get("includeTrashed") == "1",
        style=single.get("style") or DEFAULT_STYLE,
        locale=single.get("locale") or DEFAULT_LOCALE,
        linkwrap=single.get("linkwrap") == "1",
        raw=tuple(params),
    )
