"""Item endpoints."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from altero import atom, cite, serializers
from altero.api.batch import batch_write
from altero.api.deps import BaseUrlDep, ReadableLibraryDep, SessionDep, WritableLibraryDep
from altero.api.responses import (
    AtomFeed,
    entry_response,
    library_headers,
    listing_response,
    not_modified,
    object_response,
)
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.models import Item, Library
from altero.query import (
    EXPORT_FORMATS,
    ITEM_FORMATS,
    ITEM_SORT_FIELDS,
    SINGLE_OBJECT_FORMATS,
    Format,
    ListQuery,
    parse_list_query,
)
from altero.services import collections as collections_service
from altero.services import items as items_service
from altero.services import itemwrites as item_writes
from altero.services import writes
from altero.services.items import Page, Scope

router = APIRouter(tags=["items"])

#: What an Atom feed says it covers, per scope, in the words the live API uses.
#: ``{name}`` is the collection or the parent item the scope is taken from. The
#: curly quotes are upstream's, character for character, which is why the
#: ambiguous-character rule is waived rather than the punctuation changed.
FEED_DESCRIPTIONS: dict[Scope, str] = {
    Scope.ALL: "Items",
    Scope.TOP: "Top-Level Items",
    Scope.TRASH: "Deleted Items",
    Scope.CHILDREN: "Child Items of ‘{name}’",  # noqa: RUF001
    Scope.COLLECTION: "Items in Collection ‘{name}’",  # noqa: RUF001
    Scope.COLLECTION_TOP: "Top-Level Items in Collection ‘{name}’",  # noqa: RUF001
    # My Publications is a view of the library, and upstream titles its feed
    # exactly as it titles the library's own.
    Scope.PUBLICATIONS: "Items",
    Scope.PUBLICATIONS_TOP: "Top-Level Items",
}


async def feed_description(
    session: AsyncSession, library: Library, scope: Scope, key: str | None
) -> str:
    """Return what an Atom feed of ``scope`` says it covers.

    The collection or parent item is fetched only when the title names one, so
    a JSON listing never pays for it.
    """
    template = FEED_DESCRIPTIONS[scope]
    if "{name}" not in template or key is None:
        return template

    if scope is Scope.CHILDREN:
        parent = await items_service.get_item(session, library, key)
        name = parent.field_values().get("title", "")
    else:
        name = (await collections_service.get_collection(session, library, key)).name
    return template.format(name=name)


def item_query(request: Request, formats: frozenset[Format] = ITEM_FORMATS) -> ListQuery:
    return parse_list_query(
        list(request.query_params.multi_items()),
        sort_fields=ITEM_SORT_FIELDS,
        formats=formats,
    )


def _with_included(
    envelopes: list[dict[str, Any]],
    items: Sequence[Item],
    library: Library,
    query: ListQuery,
    tags: dict[int, list[tuple[str, int]]],
) -> list[dict[str, Any]]:
    """Apply ``include`` to a page of serialized items.

    ``data`` is one of several things that may be asked for rather than the
    thing itself, so a request naming only ``bib`` gets an envelope with no
    ``data`` in it. Each rendered form is produced per item, because that is
    what a client asking for ``include=bib`` on a listing wants: one
    bibliography entry beside each item, not one document for the page.
    """
    if query.include == frozenset({"data"}):
        return envelopes

    for envelope, item in zip(envelopes, items, strict=True):
        data = envelope.pop("data")
        if "data" in query.include:
            envelope["data"] = data
        if query.include & {"bib", "citation", "csljson"}:
            csl = cite.csl_item(item, library)
            if "csljson" in query.include:
                envelope["csljson"] = csl
            if "citation" in query.include:
                envelope["citation"] = cite.citation(
                    csl, style=query.style, locale=query.locale, linkwrap=query.linkwrap
                )
            if "bib" in query.include:
                envelope["bib"] = cite.bibliography(
                    [csl], style=query.style, locale=query.locale, linkwrap=query.linkwrap
                )
        for name in query.include & {str(entry) for entry in EXPORT_FORMATS}:
            keywords = [[tag for tag, _ in tags.get(item.id, [])]]
            csl_item = [cite.csl_item(item, library)]
            envelope[name] = (
                cite.ris(csl_item, keywords=keywords)
                if name == Format.RIS
                else cite.bibtex(csl_item, keywords=keywords, biblatex=name == Format.BIBLATEX)
            )
    return envelopes


async def render_items(
    session: AsyncSession,
    items: Sequence[Item],
    library: Library,
    base_url: str,
    query: ListQuery | None = None,
) -> list[dict[str, Any]]:
    """Serialize items, gathering the related data their envelopes need.

    The related data is fetched once for the whole page rather than once per
    item: a page of a hundred items would otherwise cost hundreds of round
    trips, which is invisible against a local SQLite file and dominates the
    response against a networked database.
    """
    tags = await items_service.tags_for(session, items)
    collections = await items_service.collection_keys_for(session, items)
    children = await items_service.count_children(session, items)
    parent_keys = await items_service.parent_keys_for(session, items)

    envelopes = [
        serializers.item(
            item,
            library,
            base_url,
            tags=tags.get(item.id, []),
            collections=collections.get(item.id, []),
            num_children=children.get(item.id, 0),
            parent_key=parent_keys.get(item.parent_id) if item.parent_id else None,
        )
        for item in items
    ]
    if query is None:
        return envelopes
    return _with_included(envelopes, items, library, query, tags)


async def render_item(
    session: AsyncSession,
    item: Item,
    library: Library,
    base_url: str,
    query: ListQuery | None = None,
) -> dict[str, Any]:
    """Serialize one item."""
    (rendered,) = await render_items(session, [item], library, base_url, query)
    return rendered


async def render_page(
    request: Request,
    session: AsyncSession,
    page: Page[Item],
    library: Library,
    base_url: str,
    query: ListQuery,
    describes: str = "Items",
) -> Response:
    """Render a page of items in the requested format."""
    objects: list[Any] = []
    csljson: list[Any] | None = None
    bibliography: str | None = None
    exported: str | None = None
    feed: AtomFeed | None = None

    if query.response_format is Format.JSON:
        objects = await render_items(session, page.objects, library, base_url, query)
    elif query.response_format is Format.ATOM:
        # The same envelopes JSON is built from, so an item has one definition
        # whichever format asked for it.
        envelopes = await render_items(session, page.objects, library, base_url, query)
        feed = AtomFeed(
            describes=describes,
            author=atom.author_for(library, base_url),
            entries=tuple(atom.item_entry(envelope, query.content) for envelope in envelopes),
            empty_updated=serializers.timestamp(datetime.now(UTC).replace(tzinfo=None)),
        )
    elif query.response_format is Format.CSLJSON:
        csljson = cite.csl_items(list(page.objects), library)
    elif query.response_format is Format.BIB:
        bibliography = cite.bibliography(
            cite.csl_items(list(page.objects), library),
            style=query.style,
            locale=query.locale,
            linkwrap=query.linkwrap,
        )
    elif query.response_format in EXPORT_FORMATS:
        exported = await export_items(session, list(page.objects), library, query.response_format)

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[item.key for item in page.objects],
        versions={item.key: item.version for item in page.objects},
        csljson=csljson,
        bibliography=bibliography,
        exported=exported,
        feed=feed,
    )


async def export_items(
    session: AsyncSession, items: Sequence[Item], library: Library, response_format: Format
) -> str:
    """Write items in one of the export formats.

    Tags are fetched separately because they are not part of CSL and so are not
    in what :func:`altero.cite.csl_items` produces -- but both BibTeX and RIS
    carry keywords, and a library exported without its tags has lost something
    the person put there.
    """
    csl = cite.csl_items(list(items), library)
    stored = await items_service.tags_for(session, items)
    keywords = [[name for name, _ in stored.get(item.id, [])] for item in items]

    if response_format is Format.RIS:
        return cite.ris(csl, keywords=keywords)
    return cite.bibtex(csl, keywords=keywords, biblatex=response_format is Format.BIBLATEX)


async def render_listing(
    request: Request,
    session: AsyncSession,
    library: Library,
    base_url: str,
    scope: Scope,
    key: str | None = None,
) -> Response:
    query = item_query(request)
    if (response := not_modified(request, library.version)) is not None:
        return response

    describes = (
        await feed_description(session, library, scope, key)
        if query.response_format is Format.ATOM
        else ""
    )
    page = await items_service.list_items(session, library, query, scope, key)
    return await render_page(request, session, page, library, base_url, query, describes)


@router.get("/users/{user_id}/items")
@router.get("/groups/{group_id}/items")
async def list_items(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await render_listing(request, session, library, base_url, Scope.ALL)


@router.get("/users/{user_id}/items/top")
@router.get("/groups/{group_id}/items/top")
async def list_top_items(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await render_listing(request, session, library, base_url, Scope.TOP)


@router.get("/users/{user_id}/items/trash")
@router.get("/groups/{group_id}/items/trash")
async def list_trashed_items(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await render_listing(request, session, library, base_url, Scope.TRASH)


@router.get("/users/{user_id}/items/{item_key}")
@router.get("/groups/{group_id}/items/{item_key}")
async def get_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    query = item_query(request, SINGLE_OBJECT_FORMATS)
    if (response := not_modified(request, library.version)) is not None:
        return response

    item = await items_service.get_item(session, library, item_key)

    if query.response_format is Format.ATOM:
        envelope = await render_item(session, item, library, base_url, query)
        return entry_response(
            atom.item_entry(envelope, query.content),
            atom.author_for(library, base_url),
            library.version,
        )

    if query.response_format is Format.CSLJSON:
        payload: Any = cite.csl_item(item, library)
    elif query.response_format is Format.BIB:
        payload = cite.bibliography(
            [cite.csl_item(item, library)],
            style=query.style,
            locale=query.locale,
            linkwrap=query.linkwrap,
        )
    elif query.response_format in EXPORT_FORMATS:
        payload = await export_items(session, [item], library, query.response_format)
    else:
        payload = await render_item(session, item, library, base_url, query)

    return object_response(payload, library.version, query.response_format)


@router.get("/users/{user_id}/items/{item_key}/children")
@router.get("/groups/{group_id}/items/{item_key}/children")
async def list_item_children(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    return await render_listing(request, session, library, base_url, Scope.CHILDREN, item_key)


@router.post("/users/{user_id}/items")
@router.post("/groups/{group_id}/items")
async def create_items(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    """Create or update a batch of items."""

    async def save(
        session: AsyncSession, library: Library, payload: dict[str, Any], version: int
    ) -> dict[str, Any] | None:
        item = await item_writes.save_item(
            session, library, payload, version, detect_unchanged=True
        )
        if item is None:
            return None
        await session.flush()
        return await render_item(session, item, library, base_url)

    return await batch_write(request, session, library, save)


@router.put("/users/{user_id}/items/{item_key}")
@router.put("/groups/{group_id}/items/{item_key}")
async def replace_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Replace an item outright. Properties left out are cleared."""
    return await _write_single(item_key, request, session, library, replace=True)


@router.patch("/users/{user_id}/items/{item_key}")
@router.patch("/groups/{group_id}/items/{item_key}")
async def update_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Update an item in place. Properties left out are untouched."""
    return await _write_single(item_key, request, session, library, replace=False)


async def _write_single(
    item_key: str,
    request: Request,
    session: AsyncSession,
    library: Library,
    *,
    replace: bool,
) -> Response:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise InvalidInputError("Uploaded data must be a JSON object")

    header_version = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    if header_version is not None:
        payload = {"version": header_version, **payload}

    version = await writes.bump_library_version(session, library)
    await item_writes.save_item(
        session,
        library,
        payload,
        version,
        key=item_key,
        replace=replace,
        require_version=True,
    )
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/items/{item_key}")
@router.delete("/groups/{group_id}/items/{item_key}")
async def delete_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Remove one item. Requires the version the client last saw."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    await items_service.get_item(session, library, item_key)
    version = await writes.bump_library_version(session, library)
    await item_writes.delete_items(session, library, [item_key], version)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/items")
@router.delete("/groups/{group_id}/items")
async def delete_items(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Remove up to fifty items named by the ``itemKey`` parameter."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    keys = [key for key in (request.query_params.get("itemKey") or "").split(",") if key]
    if not keys:
        raise InvalidInputError("'itemKey' parameter not provided")
    if len(keys) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(f"Cannot delete more than {writes.MAX_OBJECTS} items at a time")

    version = await writes.bump_library_version(session, library)
    await item_writes.delete_items(session, library, keys, version)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
