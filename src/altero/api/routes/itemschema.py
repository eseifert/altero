"""Endpoints describing item types, fields and creator types."""

from email.utils import format_datetime, parsedate_to_datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.itemschema import get_schema
from altero.itemschema.registry import SCHEMA_PATH

router = APIRouter(tags=["schema"])

LocaleParam = Annotated[str | None, Query(description="CSL locale code, e.g. fr-FR.")]
ItemTypeParam = Annotated[str, Query(description="Item type to describe.")]


def _last_modified() -> str:
    """Return the vendored schema's modification time as an HTTP date.

    The schema only changes when the bundled file is replaced, so its mtime is a
    truthful validator for every endpoint derived from it.
    """
    from datetime import UTC, datetime

    stamp = datetime.fromtimestamp(SCHEMA_PATH.stat().st_mtime, tz=UTC).replace(microsecond=0)
    return format_datetime(stamp, usegmt=True)


def schema_response(request: Request, payload: Any) -> Response:
    """Return ``payload`` as JSON, honouring ``If-Modified-Since``."""
    last_modified = _last_modified()
    headers = {"Last-Modified": last_modified, "Cache-Control": "public, max-age=3600"}

    if since := request.headers.get("If-Modified-Since"):
        try:
            unchanged = parsedate_to_datetime(since) >= parsedate_to_datetime(last_modified)
        except TypeError, ValueError:
            # An unparseable date is treated as no condition at all.
            unchanged = False
        if unchanged:
            return Response(status_code=304, headers=headers)

    return JSONResponse(payload, headers=headers)


@router.get("/itemTypes")
async def get_item_types(request: Request, locale: LocaleParam = None) -> Response:
    return schema_response(request, get_schema().localized_item_types(locale))


@router.get("/itemFields")
async def get_item_fields(request: Request, locale: LocaleParam = None) -> Response:
    return schema_response(request, get_schema().localized_fields(locale))


@router.get("/itemTypeFields")
async def get_item_type_fields(
    request: Request, itemType: ItemTypeParam, locale: LocaleParam = None
) -> Response:
    return schema_response(request, get_schema().localized_item_type_fields(itemType, locale))


@router.get("/itemTypeCreatorTypes")
async def get_item_type_creator_types(
    request: Request, itemType: ItemTypeParam, locale: LocaleParam = None
) -> Response:
    return schema_response(
        request, get_schema().localized_item_type_creator_types(itemType, locale)
    )


@router.get("/creatorFields")
async def get_creator_fields(request: Request, locale: LocaleParam = None) -> Response:
    return schema_response(request, get_schema().localized_creator_fields(locale))


@router.get("/items/new")
async def get_item_template(
    request: Request,
    itemType: ItemTypeParam,
    linkMode: Annotated[str | None, Query(description="Required for attachments.")] = None,
) -> Response:
    return schema_response(request, get_schema().template(itemType, linkMode))


@router.get("/schema")
async def get_full_schema(request: Request) -> Response:
    return schema_response(request, get_schema().raw)
