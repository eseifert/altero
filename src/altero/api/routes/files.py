"""Attachment files.

Uploading takes three requests: authorize, send the bytes, register. Upstream
hands out an S3 URL for the middle step; altero takes the bytes itself, so the
authorization step points back here.
"""

from pathlib import Path

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from altero.api.deps import ReadableLibraryDep, SessionDep, WritableLibraryDep
from altero.api.responses import library_headers
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.services import items as items_service
from altero.services import storage, writes

router = APIRouter(tags=["files"])

#: Largest upload accepted, so a stray request cannot fill the disk.
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


def _storage_root(request: Request) -> Path:
    return Path(request.app.state.settings.storage_path)


@router.post("/users/{user_id}/items/{item_key}/file")
@router.post("/groups/{group_id}/items/{item_key}/file")
async def upload_file(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: WritableLibraryDep,
) -> Response:
    """Authorize an upload, or register one that has finished.

    Which of the two this is depends on whether the body carries ``upload``,
    matching the protocol the client already speaks.
    """
    form = {key: str(value) for key, value in (await request.form()).items()}

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)

    if_match = request.headers.get("If-Match")
    if_none_match = request.headers.get("If-None-Match")

    if upload_key := form.get("upload"):
        upload = await storage.get_upload(session, upload_key)
        version = await writes.bump_library_version(session, library)
        await storage.register(session, item, upload, version)
        await session.commit()
        return Response(status_code=204, headers=library_headers(version))

    storage.check_preconditions(item, if_match, if_none_match)
    declared = storage.parse_authorization(form)
    if declared["filesize"] > MAX_UPLOAD_BYTES:
        raise RequestTooLargeError("File is too large")

    result = await storage.authorize(session, library, item, declared, _storage_root(request))

    if "exists" in result:
        # Nothing to send, so the attachment is already up to date.
        version = await writes.bump_library_version(session, library)
        item.version = version
        await session.commit()
        return JSONResponse(result, headers=library_headers(version))

    await session.commit()
    return JSONResponse(result, headers=library_headers(library.version))


@router.post("/storage/upload/{upload_key}")
async def receive_upload(upload_key: str, request: Request, session: SessionDep) -> Response:
    """Take the bytes of an authorized upload.

    This stands in for the storage service the upstream server hands out. The
    upload key is the credential: it was issued to a request that had already
    proved it may write to the library.
    """
    upload = await storage.get_upload(session, upload_key)

    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise RequestTooLargeError("File is too large")

    storage.store_bytes(_storage_root(request), upload, body)
    upload.received = True
    await session.commit()

    return Response(status_code=201)


@router.get("/users/{user_id}/items/{item_key}/file")
@router.get("/groups/{group_id}/items/{item_key}/file")
async def download_file(
    item_key: str, request: Request, session: SessionDep, library: ReadableLibraryDep
) -> Response:
    """Return the file attached to an item."""
    item = await items_service.get_item(session, library, item_key)
    path, fields = await storage.stored_file(item, _storage_root(request))

    return FileResponse(
        path,
        media_type=fields.get("contentType") or "application/octet-stream",
        filename=fields.get("filename") or item.key,
    )


@router.get("/users/{user_id}/items/{item_key}/file/view")
@router.get("/groups/{group_id}/items/{item_key}/file/view")
async def view_file(
    item_key: str, request: Request, session: SessionDep, library: ReadableLibraryDep
) -> Response:
    """Return the file for display rather than download."""
    item = await items_service.get_item(session, library, item_key)
    path, fields = await storage.stored_file(item, _storage_root(request))

    content_type = fields.get("contentType") or "application/octet-stream"
    if charset := fields.get("charset"):
        content_type = f"{content_type}; charset={charset}"

    return FileResponse(path, media_type=content_type)


@router.delete("/users/{user_id}/items/{item_key}/file")
@router.delete("/groups/{group_id}/items/{item_key}/file")
async def delete_file(item_key: str) -> Response:
    """Not supported: a file goes away with the item that carries it."""
    raise InvalidInputError("Delete the attachment item instead")
