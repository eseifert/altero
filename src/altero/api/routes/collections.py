"""Collection endpoints."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from altero import serializers
from altero.api.batch import batch_write
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
from altero.api.routes.items import render_page
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.models import Collection, Library
from altero.query import NAMED_SORT_FIELDS, Format, ListQuery, parse_list_query
from altero.services import collections as collections_service
from altero.services import items as items_service
from altero.services import objectwrites as object_writes
from altero.services import writes
from altero.services.collections import Page
from altero.services.items import Scope

router = APIRouter(tags=["collections"])


def collection_query(request: Request) -> ListQuery:
    return parse_list_query(
        list(request.query_params.multi_items()),
        sort_fields=NAMED_SORT_FIELDS,
        default_sort="title",
    )


async def render_collection(
    session: AsyncSession, collection: Collection, library: Library, base_url: str
) -> dict[str, Any]:
    return serializers.collection(
        collection,
        library,
        base_url,
        num_collections=await collections_service.count_subcollections(session, collection),
        num_items=await collections_service.count_items(session, collection),
        parent_key=await collections_service.parent_key_of(session, collection),
    )


async def _render_page(
    request: Request,
    session: AsyncSession,
    page: Page[Collection],
    library: Library,
    base_url: str,
    query: ListQuery,
) -> Response:
    objects: list[Any] = []
    if query.response_format is Format.JSON:
        objects = [
            await render_collection(session, collection, library, base_url)
            for collection in page.objects
        ]

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[collection.key for collection in page.objects],
        versions={collection.key: collection.version for collection in page.objects},
    )


@router.get("/users/{user_id}/collections")
@router.get("/groups/{group_id}/collections")
async def list_collections(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    query = collection_query(request)
    if (response := not_modified(request, library.version)) is not None:
        return response

    page = await collections_service.list_collections(session, library, query)
    return await _render_page(request, session, page, library, base_url, query)


@router.get("/users/{user_id}/collections/top")
@router.get("/groups/{group_id}/collections/top")
async def list_top_collections(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    query = collection_query(request)
    page = await collections_service.list_collections(session, library, query, top_only=True)
    return await _render_page(request, session, page, library, base_url, query)


@router.get("/users/{user_id}/collections/{collection_key}")
@router.get("/groups/{group_id}/collections/{collection_key}")
async def get_collection(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    if (response := not_modified(request, library.version)) is not None:
        return response

    collection = await collections_service.get_collection(session, library, collection_key)
    return object_response(
        await render_collection(session, collection, library, base_url), library.version
    )


@router.get("/users/{user_id}/collections/{collection_key}/collections")
@router.get("/groups/{group_id}/collections/{collection_key}/collections")
async def list_subcollections(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    query = collection_query(request)
    page = await collections_service.list_collections(
        session, library, query, parent_key=collection_key
    )
    return await _render_page(request, session, page, library, base_url, query)


@router.get("/users/{user_id}/collections/{collection_key}/items")
@router.get("/groups/{group_id}/collections/{collection_key}/items")
async def list_collection_items(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    from altero.api.routes.items import item_query

    query = item_query(request)
    page = await items_service.list_items(session, library, query, Scope.COLLECTION, collection_key)
    return await render_page(request, session, page, library, base_url, query)


@router.get("/users/{user_id}/collections/{collection_key}/items/top")
@router.get("/groups/{group_id}/collections/{collection_key}/items/top")
async def list_top_collection_items(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    from altero.api.routes.items import item_query

    query = item_query(request)
    page = await items_service.list_items(
        session, library, query, Scope.COLLECTION_TOP, collection_key
    )
    return await render_page(request, session, page, library, base_url, query)


@router.post("/users/{user_id}/collections")
@router.post("/groups/{group_id}/collections")
async def create_collections(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    """Create or update a batch of collections."""

    async def save(
        session: AsyncSession, library: Library, payload: dict[str, Any], version: int
    ) -> dict[str, Any]:
        collection = await object_writes.save_collection(session, library, payload, version)
        return await render_collection(session, collection, library, base_url)

    return await batch_write(request, session, library, save)


@router.put("/users/{user_id}/collections/{collection_key}")
@router.put("/groups/{group_id}/collections/{collection_key}")
async def replace_collection(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Replace one collection."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise InvalidInputError("Uploaded data must be a JSON object")

    header_version = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    if header_version is not None:
        payload = {"version": header_version, **payload}

    await collections_service.get_collection(session, library, collection_key)
    version = await writes.bump_library_version(session, library)
    await object_writes.save_collection(
        session, library, payload, version, key=collection_key, require_version=True
    )
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/collections/{collection_key}")
@router.delete("/groups/{group_id}/collections/{collection_key}")
async def delete_collection(
    collection_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Remove one collection. Nested collections move up to its parent."""
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    await collections_service.get_collection(session, library, collection_key)
    version = await writes.bump_library_version(session, library)
    await object_writes.delete_collections(session, library, [collection_key], version)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/collections")
@router.delete("/groups/{group_id}/collections")
async def delete_collections(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Remove up to fifty collections named by ``collectionKey``."""
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    keys = [k for k in (request.query_params.get("collectionKey") or "").split(",") if k]
    if not keys:
        raise InvalidInputError("'collectionKey' parameter not provided")
    if len(keys) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(
            f"Cannot delete more than {writes.MAX_OBJECTS} collections at a time"
        )

    version = await writes.bump_library_version(session, library)
    await object_writes.delete_collections(session, library, keys, version)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
