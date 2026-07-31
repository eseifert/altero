"""Tag endpoints."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

from altero import serializers
from altero.api.deps import (
    BaseUrlDep,
    ReadableLibraryDep,
    SessionDep,
    WritableLibraryDep,
)
from altero.api.responses import (
    library_headers,
    listing_response,
    not_modified,
    object_response,
)
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.models import Item, Library
from altero.query import TAG_SORT_FIELDS, Format, ListQuery, parse_list_query
from altero.search import parse_expressions
from altero.services import items as items_service
from altero.services import objectwrites as object_writes
from altero.services import tags as tags_service
from altero.services import writes
from altero.services.items import Page, Scope
from altero.services.tags import TagSummary

router = APIRouter(tags=["tags"])


def _render_tags(
    request: Request,
    query: ListQuery,
    page: Page[TagSummary],
    library: Library,
    base_url: str,
) -> Response:
    """Render a page of tags in the requested format."""
    objects: list[Any] = []
    if query.response_format is Format.JSON:
        objects = [
            serializers.tag(s.name, s.type, s.num_items, library, base_url) for s in page.objects
        ]

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[s.name for s in page.objects],
        versions={s.name: s.version for s in page.objects},
    )


def tag_query(request: Request) -> ListQuery:
    return parse_list_query(
        list(request.query_params.multi_items()),
        sort_fields=TAG_SORT_FIELDS,
        default_sort="title",
        tag_endpoint=True,
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

    objects: list[Any] = []
    if query.response_format is Format.JSON:
        objects = [
            serializers.tag(
                summary.name,
                summary.type,
                summary.num_items,
                library,
                base_url,
            )
            for summary in page.objects
        ]

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[summary.name for summary in page.objects],
        versions={summary.name: summary.version for summary in page.objects},
    )


@router.get("/users/{user_id}/tags/{tag_name}")
@router.get("/groups/{group_id}/tags/{tag_name}")
async def get_tag(
    tag_name: str,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    summary = await tags_service.get_tag(session, library, tag_name)
    return object_response(
        serializers.tag(
            summary.name,
            summary.type,
            summary.num_items,
            library,
            base_url,
        ),
        library.version,
    )


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
) -> Response:
    """Remove up to fifty tags named by the ``tag`` parameter.

    Alternatives are separated by ``||`` in the usual search syntax, so one
    parameter can name several tags.
    """
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    names = [
        value
        for expression in parse_expressions(request.query_params.getlist("tag"))
        for value in expression.values
    ]
    if not names:
        raise InvalidInputError("'tag' parameter not provided")
    if len(names) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(f"Cannot delete more than {writes.MAX_OBJECTS} tags at a time")

    version = await writes.bump_library_version(session, library)
    await object_writes.delete_tags(session, library, names, version)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
