"""Full-text content of attachments.

The client extracts text from a PDF or web page and uploads it here so that
searching works on every device rather than only the one holding the file.
"""

from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.batch import batch_write
from altero.api.deps import AccessDep, ReadableLibraryDep, SessionDep, WritableLibraryDep
from altero.api.responses import library_headers
from altero.errors import InvalidInputError
from altero.models import Library
from altero.services import fulltext as fulltext_service
from altero.services import items as items_service
from altero.services import writes

router = APIRouter(tags=["fulltext"])


@router.get("/users/{user_id}/fulltext")
@router.get("/groups/{group_id}/fulltext")
async def list_fulltext_versions(
    request: Request, session: SessionDep, library: ReadableLibraryDep, access: AccessDep
) -> Response:
    """Return the version of every attachment's text, keyed by item key.

    A key and a version for every indexed attachment in the library, which is
    exactly the shape a confinement has to reach: it names objects. It is
    narrowed by the same ``permit`` an item listing is.
    """
    raw = request.query_params.get("since")
    try:
        since = int(raw) if raw else 0
    except ValueError:
        raise InvalidInputError(f"Invalid 'since' value '{raw}'") from None

    versions = await fulltext_service.list_versions(session, library, since, permit=access)
    return JSONResponse(versions, headers=library_headers(library.version))


@router.post("/users/{user_id}/fulltext")
@router.post("/groups/{group_id}/fulltext")
async def upload_fulltext(
    request: Request, session: SessionDep, library: WritableLibraryDep, access: AccessDep
) -> Response:
    """Store full text for a batch of items.

    This is how the desktop client uploads: one request carrying the text of
    every attachment it has indexed since the last sync. Unlike the other batch
    writes, the version header is required, so a client cannot upload against a
    library that moved underneath it.
    """

    async def save(
        session: AsyncSession, library: Library, payload: dict[str, Any], version: int
    ) -> dict[str, Any]:
        return await fulltext_service.save_batch_entry(
            session, library, payload, version, permit=access
        )

    return await batch_write(request, session, library, save, require_version=True)


@router.get("/users/{user_id}/items/{item_key}/fulltext")
@router.get("/groups/{group_id}/items/{item_key}/fulltext")
async def get_fulltext(
    item_key: str, session: SessionDep, library: ReadableLibraryDep, access: AccessDep
) -> Response:
    """Return the stored text of one attachment."""
    item = await items_service.get_item(session, library, item_key, permit=access)
    stored = await fulltext_service.get_content(session, item)

    return JSONResponse(fulltext_service.render(stored), headers=library_headers(stored.version))


@router.put("/users/{user_id}/items/{item_key}/fulltext")
@router.put("/groups/{group_id}/items/{item_key}/fulltext")
async def put_fulltext(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
    access: AccessDep,
) -> Response:
    """Store the text of one attachment."""
    payload = await request.json()

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key, permit=access)

    version = await writes.bump_library_version(session, library)
    await fulltext_service.save_content(session, library, item, payload, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
