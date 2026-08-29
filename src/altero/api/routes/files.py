"""Attachment files.

Uploading takes three requests: authorize, send the bytes, register. Upstream
hands out an S3 URL for the middle step; altero takes the bytes itself, so the
authorization step points back here.
"""

from pathlib import Path

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from altero.api.deps import (
    AccessDep,
    BaseUrlDep,
    FileReadableLibraryDep,
    FileWritableLibraryDep,
    SessionDep,
)
from altero.api.responses import library_headers
from altero.errors import NotFoundError, RequestTooLargeError
from altero.models import Item
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
    library: FileWritableLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
) -> Response:
    """Authorize an upload, or register one that has finished.

    Which of the two this is depends on whether the body carries ``upload``,
    matching the protocol the client already speaks.
    """
    form = {key: str(value) for key, value in (await request.form()).items()}

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)
    # Putting bytes on an attachment is a change to that attachment, so a member
    # restricted to their own items is held to the same line here as anywhere
    # else. The group's own `fileEditing` policy has already been applied.
    access.require_change(item.created_by_user_id)

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

    result = await storage.authorize(
        session, library, item, declared, _storage_root(request), base_url
    )

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


async def _file_response(item: Item, root: Path, *, expected_md5: str | None = None) -> Response:
    """Return the bytes attached to an item, described as what they are.

    One definition, so the route behind an API key and the route behind a
    download permission cannot come to disagree about what a file is called or
    what it holds.
    """
    path, fields = await storage.stored_file(item, root)

    if expected_md5 is not None and fields["md5"] != expected_md5:
        # The file moved on between the redirect and this request. Serving the
        # new bytes would break the promise the 302 made in `Zotero-File-MD5`.
        raise NotFoundError("File not found")

    if storage.is_compressed(path, fields["md5"]):
        # Describing the archive as the file it holds would be a lie in the one
        # header a browser acts on.
        return FileResponse(path, media_type="application/zip", filename=f"{item.key}.zip")

    return FileResponse(
        path,
        media_type=fields.get("contentType") or "application/octet-stream",
        filename=fields.get("filename") or item.key,
    )


@router.get("/users/{user_id}/items/{item_key}/file")
@router.get("/groups/{group_id}/items/{item_key}/file")
async def download_file(
    item_key: str, request: Request, session: SessionDep, library: FileReadableLibraryDep
) -> Response:
    """Redirect to the file attached to an item, describing it in the headers.

    Upstream answers with a 302 to S3 and hangs the file's metadata on that
    redirect. The client reads it there and nowhere else, so a 200 with the
    bytes -- however it is labelled -- reaches `processDownload` with nothing
    set and fails with "'data.mtime' not set". altero has no S3, so the
    redirect points back at itself; what matters is that it is a redirect.

    The client also uses the three headers to decide it need not download at
    all: a local file whose modification time matches means it never asks for
    the bytes, which is why they are on the 302 rather than on the response
    carrying them.

    Where it points is the part that has to be a permission rather than a path.
    The client does not follow this redirect -- it reads the headers off it and
    then makes a *second, fresh* request for the location, carrying none of the
    first one's headers -- so whatever authorizes that request has to be in the
    URL. Upstream puts a presigned S3 URL there; altero grants one short-lived
    permission for this one file. See services/storage.authorize_download.
    """
    item = await items_service.get_item(session, library, item_key)
    path, fields = await storage.stored_file(item, _storage_root(request))

    compressed = storage.is_compressed(path, fields["md5"])
    permission = await storage.authorize_download(session, library, item, fields["md5"])
    await session.commit()

    return Response(
        status_code=302,
        headers={
            "Location": f"/storage/download/{permission.key}",
            "Zotero-File-Modification-Time": fields.get("mtime") or "0",
            "Zotero-File-MD5": fields["md5"],
            "Zotero-File-Compressed": "Yes" if compressed else "No",
            # The location is a credential, so no shared cache may keep it and
            # hand it to the next caller asking for this file.
            "Cache-Control": "no-store",
        },
    )


@router.get("/users/{user_id}/items/{item_key}/file/content")
@router.get("/groups/{group_id}/items/{item_key}/file/content")
async def download_file_content(
    item_key: str, request: Request, session: SessionDep, library: FileReadableLibraryDep
) -> Response:
    """Return the bytes of the file attached to an item, behind an API key.

    Not where the redirect lands -- that is `/storage/download/<key>`, which
    the client can reach without a header. This is the same bytes for a caller
    that has a key and would rather ask for them directly, which is every
    caller that is not the desktop client's file sync.
    """
    item = await items_service.get_item(session, library, item_key)
    return await _file_response(item, _storage_root(request))


@router.get("/storage/download/{download_key}")
async def send_download(download_key: str, request: Request, session: SessionDep) -> Response:
    """Return the bytes the redirect granted permission for.

    This stands in for the presigned S3 URL upstream hands out, and the
    permission is the credential: it was issued to a request that had already
    proved it may read the library. No API key is taken here, and none is
    accepted -- the same shape as `/storage/upload/<key>` in the other
    direction.

    The digest is checked against the one the redirect promised, so a
    permission granted for one file cannot be spent on whatever replaced it.
    """
    permission = await storage.open_download(session, download_key)

    item = await session.get(Item, permission.item_id)
    if item is None:
        raise NotFoundError("File not found")

    return await _file_response(item, _storage_root(request), expected_md5=permission.md5)


@router.get("/users/{user_id}/items/{item_key}/file/view")
@router.get("/groups/{group_id}/items/{item_key}/file/view")
async def view_file(
    item_key: str, request: Request, session: SessionDep, library: FileReadableLibraryDep
) -> Response:
    """Return the file for display rather than download."""
    item = await items_service.get_item(session, library, item_key)
    path, fields = await storage.stored_file(item, _storage_root(request))

    content_type = fields.get("contentType") or "application/octet-stream"
    if charset := fields.get("charset"):
        content_type = f"{content_type}; charset={charset}"

    return FileResponse(path, media_type=content_type)
