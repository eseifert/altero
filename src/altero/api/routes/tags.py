"""Tag endpoints."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

from altero import serializers
from altero.api.deps import BaseUrlDep, ReadableLibraryDep, SessionDep
from altero.api.responses import listing_response, not_modified, object_response
from altero.models import Item
from altero.query import TAG_SORT_FIELDS, Format, ListQuery, parse_list_query
from altero.services import items as items_service
from altero.services import tags as tags_service

router = APIRouter(tags=["tags"])


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
                version=summary.version,
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
            version=summary.version,
        ),
        library.version,
    )


@router.get("/users/{user_id}/items/{item_key}/tags")
@router.get("/groups/{group_id}/items/{item_key}/tags")
async def list_item_tags(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    query = tag_query(request)
    item = await items_service.get_item(session, library, item_key)
    scope = select(Item.id).where(Item.id == item.id)

    page = await tags_service.list_tags(session, library, query, item_scope=scope)

    objects = [
        serializers.tag(
            summary.name,
            summary.type,
            summary.num_items,
            library,
            base_url,
            version=summary.version,
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
