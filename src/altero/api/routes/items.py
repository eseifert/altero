"""Item endpoints."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from altero import serializers
from altero.api.batch import batch_write
from altero.api.deps import BaseUrlDep, ReadableLibraryDep, SessionDep, WritableLibraryDep
from altero.api.responses import (
    library_headers,
    listing_response,
    not_modified,
    object_response,
)
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.models import Item, Library
from altero.query import ITEM_SORT_FIELDS, ListQuery, parse_list_query
from altero.services import items as items_service
from altero.services import itemwrites as item_writes
from altero.services import writes
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
    ) -> dict[str, Any]:
        item = await item_writes.save_item(session, library, payload, version)
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
