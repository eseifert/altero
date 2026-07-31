"""Saved search endpoints."""

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
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.models import Library
from altero.query import NAMED_SORT_FIELDS, Format, ListQuery, parse_list_query
from altero.services import objectwrites as object_writes
from altero.services import searches as searches_service
from altero.services import writes

router = APIRouter(tags=["searches"])


def search_query(request: Request) -> ListQuery:
    return parse_list_query(
        list(request.query_params.multi_items()),
        sort_fields=NAMED_SORT_FIELDS,
        default_sort="title",
    )


@router.get("/users/{user_id}/searches")
@router.get("/groups/{group_id}/searches")
async def list_searches(
    request: Request, session: SessionDep, library: ReadableLibraryDep, base_url: BaseUrlDep
) -> Response:
    query = search_query(request)
    if (response := not_modified(request, library.version)) is not None:
        return response

    page = await searches_service.list_searches(session, library, query)

    objects: list[Any] = []
    if query.response_format is Format.JSON:
        objects = [serializers.saved_search(search, library, base_url) for search in page.objects]

    return listing_response(
        request,
        query,
        version=page.library_version,
        total=page.total,
        objects=objects,
        keys=[search.key for search in page.objects],
        versions={search.key: search.version for search in page.objects},
    )


@router.get("/users/{user_id}/searches/{search_key}")
@router.get("/groups/{group_id}/searches/{search_key}")
async def get_search(
    search_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    if (response := not_modified(request, library.version)) is not None:
        return response

    search = await searches_service.get_search(session, library, search_key)
    return object_response(serializers.saved_search(search, library, base_url), library.version)


@router.post("/users/{user_id}/searches")
@router.post("/groups/{group_id}/searches")
async def create_searches(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    """Create or update a batch of saved searches."""

    async def save(
        session: AsyncSession, library: Library, payload: dict[str, Any], version: int
    ) -> dict[str, Any]:
        search = await object_writes.save_search(session, library, payload, version)
        return serializers.saved_search(search, library, base_url)

    return await batch_write(request, session, library, save)


@router.delete("/users/{user_id}/searches/{search_key}")
@router.delete("/groups/{group_id}/searches/{search_key}")
async def delete_search(
    search_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Remove one saved search."""
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    await searches_service.get_search(session, library, search_key)
    version = await writes.bump_library_version(session, library)
    await object_writes.delete_searches(session, library, [search_key], version)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/searches")
@router.delete("/groups/{group_id}/searches")
async def delete_searches(
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Remove up to fifty saved searches named by ``searchKey``."""
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    keys = [k for k in (request.query_params.get("searchKey") or "").split(",") if k]
    if not keys:
        raise InvalidInputError("'searchKey' parameter not provided")
    if len(keys) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(
            f"Cannot delete more than {writes.MAX_OBJECTS} searches at a time"
        )

    version = await writes.bump_library_version(session, library)
    await object_writes.delete_searches(session, library, keys, version)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
