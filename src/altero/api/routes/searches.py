"""Saved search endpoints."""

from typing import Any

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response

from altero import serializers
from altero.api.deps import BaseUrlDep, ReadableLibraryDep, SessionDep
from altero.api.responses import listing_response, not_modified, object_response
from altero.query import NAMED_SORT_FIELDS, Format, ListQuery, parse_list_query
from altero.services import searches as searches_service

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
