"""Item endpoints."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from altero import serializers
from altero.api.deps import BaseUrlDep, ReadableLibraryDep, SessionDep
from altero.api.responses import listing_response, not_modified, object_response
from altero.models import Item, Library
from altero.query import ITEM_SORT_FIELDS, ListQuery, parse_list_query
from altero.services import items as items_service
from altero.services.items import Page, Scope

router = APIRouter(tags=["items"])


def item_query(request: Request) -> ListQuery:
    return parse_list_query(list(request.query_params.multi_items()), sort_fields=ITEM_SORT_FIELDS)


async def render_item(
    session: AsyncSession, item: Item, library: Library, base_url: str
) -> dict[str, Any]:
    """Serialize one item, gathering the related data its envelope needs."""
    parent_key = None
    if item.parent_id is not None:
        parent = await session.get(Item, item.parent_id)
        parent_key = parent.key if parent else None

    return serializers.item(
        item,
        library,
        base_url,
        tags=await items_service.tags_for(session, item),
        collections=await items_service.collection_keys_for(session, item),
        num_children=await items_service.count_children(session, item),
        parent_key=parent_key,
    )


async def render_page(
    request: Request,
    session: AsyncSession,
    page: Page[Item],
    library: Library,
    base_url: str,
    query: ListQuery,
) -> Response:
    """Render a page of items in the requested format."""
    from altero.query import Format

    objects: list[Any] = []
    if query.response_format is Format.JSON:
        objects = [await render_item(session, item, library, base_url) for item in page.objects]

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[item.key for item in page.objects],
        versions={item.key: item.version for item in page.objects},
    )


async def _listing(
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

    page = await items_service.list_items(session, library, query, scope, key)
    return await render_page(request, session, page, library, base_url, query)


@router.get("/users/{user_id}/items")
@router.get("/groups/{group_id}/items")
async def list_items(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await _listing(request, session, library, base_url, Scope.ALL)


@router.get("/users/{user_id}/items/top")
@router.get("/groups/{group_id}/items/top")
async def list_top_items(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await _listing(request, session, library, base_url, Scope.TOP)


@router.get("/users/{user_id}/items/trash")
@router.get("/groups/{group_id}/items/trash")
async def list_trashed_items(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await _listing(request, session, library, base_url, Scope.TRASH)


@router.get("/users/{user_id}/items/{item_key}")
@router.get("/groups/{group_id}/items/{item_key}")
async def get_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    if (response := not_modified(request, library.version)) is not None:
        return response

    item = await items_service.get_item(session, library, item_key)
    return object_response(await render_item(session, item, library, base_url), library.version)


@router.get("/users/{user_id}/items/{item_key}/children")
@router.get("/groups/{group_id}/items/{item_key}/children")
async def list_item_children(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    return await _listing(request, session, library, base_url, Scope.CHILDREN, item_key)
