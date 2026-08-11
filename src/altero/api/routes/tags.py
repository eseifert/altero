"""Tag endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

from altero import atom, serializers
from altero.api.deps import (
    AccessDep,
    BaseUrlDep,
    ReadableLibraryDep,
    SessionDep,
    WritableLibraryDep,
)
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
    OBJECT_FORMATS,
    SINGLE_NAMED_FORMATS,
    TAG_SORT_FIELDS,
    Format,
    ListQuery,
    parse_list_query,
)
from altero.search import parse_expressions
from altero.services import items as items_service
from altero.services import objectwrites as object_writes
from altero.services import tags as tags_service
from altero.services import writes
from altero.services.items import Page, Scope
from altero.services.tags import TagSummary

router = APIRouter(tags=["tags"])


def _updated(summary: TagSummary) -> str:
    """Return the ``updated`` an Atom entry for ``summary`` carries.

    A tag has no timestamp of its own, so this is the newest change to an item
    that carries it. Falls back to now for the case that cannot happen through
    the API -- a tag attached to nothing is deleted rather than kept.
    """
    when = summary.last_modified or datetime.now(UTC).replace(tzinfo=None)
    return serializers.timestamp(when)


def _tag_feed(
    query: ListQuery,
    envelopes: list[dict[str, Any]],
    page: Page[TagSummary],
    library: Library,
    base_url: str,
) -> AtomFeed:
    return AtomFeed(
        describes="Tags",
        author=atom.author_for(library, base_url),
        entries=tuple(
            atom.tag_entry(envelope, query.content, updated=_updated(summary))
            for envelope, summary in zip(envelopes, page.objects, strict=True)
        ),
        empty_updated=serializers.timestamp(datetime.now(UTC).replace(tzinfo=None)),
    )


def _render_tags(
    request: Request,
    query: ListQuery,
    page: Page[TagSummary],
    library: Library,
    base_url: str,
) -> Response:
    """Render a page of tags in the requested format."""
    objects: list[Any] = []
    feed: AtomFeed | None = None

    if query.response_format in (Format.JSON, Format.ATOM):
        envelopes = [
            serializers.tag(s.name, s.type, s.num_items, library, base_url) for s in page.objects
        ]
        if query.response_format is Format.JSON:
            objects = envelopes
        else:
            feed = _tag_feed(query, envelopes, page, library, base_url)

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[s.name for s in page.objects],
        versions={s.name: s.version for s in page.objects},
        feed=feed,
    )


def tag_query(request: Request, formats: frozenset[Format] = OBJECT_FORMATS) -> ListQuery:
    return parse_list_query(
        list(request.query_params.multi_items()),
        sort_fields=TAG_SORT_FIELDS,
        default_sort="title",
        tag_endpoint=True,
        formats=formats,
    )


@router.get("/users/{user_id}/tags")
@router.get("/groups/{group_id}/tags")
async def list_tags(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    query = tag_query(request)
    if (response := not_modified(request, library.version)) is not None:
        return response

    page = await tags_service.list_tags(session, library, query)
    return _render_tags(request, query, page, library, base_url)


@router.get("/users/{user_id}/tags/{tag_name}")
@router.get("/groups/{group_id}/tags/{tag_name}")
async def get_tag(
    tag_name: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    query = tag_query(request, SINGLE_NAMED_FORMATS)
    summary = await tags_service.get_tag(session, library, tag_name)
    envelope = serializers.tag(summary.name, summary.type, summary.num_items, library, base_url)

    if query.response_format is Format.ATOM:
        return entry_response(
            atom.tag_entry(envelope, query.content, updated=_updated(summary)),
            atom.author_for(library, base_url),
            library.version,
        )

    return object_response(envelope, library.version)


@router.patch("/users/{user_id}/tags/{tag_name}")
@router.patch("/groups/{group_id}/tags/{tag_name}")
async def rename_tag(
    tag_name: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Rename one tag, taking ``{"tag": "<new name>"}``.

    Not upstream's. The dataserver serves ``GET`` and ``DELETE`` here and
    nothing else, and renaming has been asked of it since 2016
    (zotero/dataserver#108) without an answer, so there is no reference to
    copy and this endpoint is altero's own -- see ``docs/compatibility.md``.
    It is modelled on the one place the operation does exist: the desktop
    client's ``Zotero.Tags.rename``, whose behaviour
    :func:`altero.services.objectwrites.rename_tag` follows.

    ``PATCH`` rather than ``PUT`` because a tag is more than its name to the
    API -- the envelope carries a type and a count, and neither is given here.
    The answer is ``204``, as the tag's own URL has moved and there is nothing
    at the old one to return.

    ``If-Unmodified-Since-Version`` is required, as it is for ``DELETE
    <prefix>/tags``: this rewrites every item carrying the tag, and a client
    that has not seen the library's current state cannot know what that is.
    """
    payload = await request.json()
    if not isinstance(payload, dict) or "tag" not in payload:
        raise InvalidInputError("'tag' property not provided")
    new_name = object_writes.clean_tag_name(str(payload["tag"]))

    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    # Both before a version is spent: a tag that is not there is a 404 whatever
    # the body says, and a rename to the name it already has changes nothing, so
    # it must not move the library on. The client returns early on the same two.
    summary = await tags_service.get_tag(session, library, tag_name)
    if new_name == summary.name:
        return Response(status_code=204, headers=library_headers(library.version))

    version = await writes.bump_library_version(session, library)
    await object_writes.rename_tag(session, library, tag_name, new_name, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


async def _scoped_tags(
    request: Request,
    session: SessionDep,
    library: Library,
    base_url: str,
    scope: Scope,
    key: str | None = None,
) -> Response:
    """List the tags carried by a scoped set of items."""
    from altero.api.routes.items import item_query

    query = tag_query(request)
    # The item scope is filtered by the item parameters, the tags by the tag
    # ones, which is why two queries are parsed from one request.
    item_scope = await items_service.item_ids_in_scope(
        session, library, item_query(request), scope, key
    )
    page = await tags_service.list_tags(session, library, query, item_scope=item_scope)

    return _render_tags(request, query, page, library, base_url)


# Registered before `/items/{item_key}/tags`, which would otherwise capture
# `top` and `trash` as item keys.
@router.get("/users/{user_id}/items/top/tags")
@router.get("/groups/{group_id}/items/top/tags")
async def list_top_item_tags(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await _scoped_tags(request, session, library, base_url, Scope.TOP)


@router.get("/users/{user_id}/items/trash/tags")
@router.get("/groups/{group_id}/items/trash/tags")
async def list_trashed_item_tags(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await _scoped_tags(request, session, library, base_url, Scope.TRASH)


@router.get("/users/{user_id}/items/tags")
@router.get("/groups/{group_id}/items/tags")
async def list_all_item_tags(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await _scoped_tags(request, session, library, base_url, Scope.ALL)


@router.get("/users/{user_id}/collections/{collection_key}/items/top/tags")
@router.get("/groups/{group_id}/collections/{collection_key}/items/top/tags")
async def list_top_collection_item_tags(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    return await _scoped_tags(
        request, session, library, base_url, Scope.COLLECTION_TOP, collection_key
    )


@router.get("/users/{user_id}/collections/{collection_key}/items/tags")
@router.get("/groups/{group_id}/collections/{collection_key}/items/tags")
async def list_collection_item_tags(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    return await _scoped_tags(request, session, library, base_url, Scope.COLLECTION, collection_key)


@router.get("/users/{user_id}/collections/{collection_key}/tags")
@router.get("/groups/{group_id}/collections/{collection_key}/tags")
async def list_collection_tags(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    """List the tags used within one collection."""
    return await _scoped_tags(request, session, library, base_url, Scope.COLLECTION, collection_key)


@router.get("/users/{user_id}/items/{item_key}/tags")
@router.get("/groups/{group_id}/items/{item_key}/tags")
async def list_item_tags(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    """List the tags carried by one item."""
    query = tag_query(request)
    item = await items_service.get_item(session, library, item_key)
    scope = select(Item.id).where(Item.id == item.id)

    page = await tags_service.list_tags(session, library, query, item_scope=scope)
    return _render_tags(request, query, page, library, base_url)


@router.delete("/users/{user_id}/tags")
@router.delete("/groups/{group_id}/tags")
async def delete_tags(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Remove up to fifty tags named by the ``tag`` parameter.

    Alternatives are separated by ``||`` in the usual search syntax, so one
    parameter can name several tags. ``tags`` is accepted as well, because the
    desktop client builds its deletions with that name; it splits on a bare
    ``||`` rather than a spaced one, matching how the client joins them.

    A request naming no tag deletes nothing and still answers 204. That is what
    upstream does, and it is the case that actually arrives: the client puts its
    names in ``tags``, which its own parameter filter then drops, so the request
    reaches the server bare. Answering 400 would abort the sync, since the client
    accepts only 204 or 412 here.
    """
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    names = [
        value
        for expression in parse_expressions(request.query_params.getlist("tag"))
        for value in expression.values
    ]
    for value in request.query_params.getlist("tags"):
        names.extend(name for name in value.split("||") if name)

    if not names:
        return Response(status_code=204, headers=library_headers(library.version))
    if len(names) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(f"Cannot delete more than {writes.MAX_OBJECTS} tags at a time")

    version = await writes.bump_library_version(session, library)
    await object_writes.delete_tags(session, library, names, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
