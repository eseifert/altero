"""Taking a whole library out of the browser, and putting one back.

The rest of ``/web`` reads libraries and writes only to the account. This is the
one place where the browser writes to a library, and it does so wholesale: a
restore replaces everything the target library holds. So both ends are narrow.

Exporting is offered to whoever administers the library -- its owner for a
personal one, an administrator for a group. Restoring is the owner's alone,
because it destroys what was there, which is the same reason deleting a group
is; and it asks for the account password again, because a session cookie is
what somebody who borrowed an unlocked laptop already has.

The target library is decided here, from who is signed in, and passed to
:func:`altero.services.transfer.import_library` as ``into``. The manifest in
the uploaded file names a library too, and it is *not* what decides: an archive
naming ``user/2`` would otherwise be restored over user 2's library by anyone
who could upload it.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import ForbiddenError, NotFoundError
from altero.models import Library, LibraryType, User
from altero.services import account, groups, transfer

router = APIRouter(prefix="/web", tags=["web"])

#: Read from the upload a megabyte at a time rather than in one string. An
#: archive carries every attachment in the library, so its size is the size of
#: somebody's PDFs and not something to hold in memory.
CHUNK = 1 << 20


async def _library_or_404(session: SessionDep, library_id: int) -> Library:
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")
    return library


async def _may_export(session: SessionDep, library: Library, user: User) -> None:
    """Allow the owner of a personal library, or a group's administrators.

    An archive holds more than the interface shows: every version, the deletion
    log, and the attachment bytes. A member who can read the library can read
    all of it item by item, so this is not secrecy -- it is that handing out the
    library as one file is an administrator's act.
    """
    if library.type is LibraryType.USER:
        if library.owner_id != user.id:
            raise ForbiddenError("That is not your library")
        return
    await groups.require_admin(session, library, user.id)


async def _may_import(session: SessionDep, library: Library, user: User) -> None:
    """Allow the owner, and nobody else.

    Restoring replaces everything in the library and there is no trash around
    one, exactly as with deleting a group -- so it is held to the same person.
    """
    if library.type is LibraryType.USER:
        if library.owner_id != user.id:
            raise ForbiddenError("That is not your library")
        return
    await groups.require_owner(session, library, user.id)


@router.get("/libraries/{library_id}/archive")
async def download_archive(
    request: Request, session: SessionDep, user: CurrentUserDep, library_id: int
) -> Response:
    """Write the library to an archive and send it.

    Built on disk and streamed from there rather than assembled in memory: with
    the attachments in it, an archive is as large as the library. The temporary
    copy is removed once the response has been sent, whether or not the browser
    stayed to the end of it.
    """
    library = await _library_or_404(session, library_id)
    await _may_export(session, library, user)

    workspace = Path(tempfile.mkdtemp(prefix="altero-export-"))
    name = f"altero-{library.type.value}-{library.owner_id}.zip"
    try:
        written = await transfer.export_library(
            session,
            library_type=library.type,
            owner_id=library.owner_id,
            storage_root=Path(request.app.state.settings.storage_path),
            destination=workspace / name,
        )
    except BaseException:
        shutil.rmtree(workspace, ignore_errors=True)
        raise

    return FileResponse(
        written,
        media_type="application/zip",
        filename=name,
        background=BackgroundTask(shutil.rmtree, workspace, ignore_errors=True),
    )


@router.post("/libraries/{library_id}/archive")
async def restore_archive(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    _csrf: CsrfDep,
    archive: Annotated[UploadFile, File()],
    current_password: Annotated[str, Form(alias="currentPassword")],
    replace: Annotated[bool, Form()] = False,
) -> Response:
    """Restore an uploaded archive into this library.

    ``replace`` is the difference between filling an empty library and throwing
    away what is in one. Without it a library with anything in it is refused,
    rather than merged: two libraries in one set of keys is not something a
    client could be asked to make sense of.
    """
    library = await _library_or_404(session, library_id)
    await _may_import(session, library, user)
    account.require_password(user, current_password)

    workspace = Path(tempfile.mkdtemp(prefix="altero-import-"))
    try:
        uploaded = workspace / "archive.zip"
        with uploaded.open("wb") as sink:
            while chunk := await archive.read(CHUNK):
                sink.write(chunk)

        manifest = transfer.read_manifest(uploaded)
        restored = await transfer.import_library(
            session,
            archive=uploaded,
            storage_root=Path(request.app.state.settings.storage_path),
            replace=replace,
            into=library,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return JSONResponse(
        {
            "library": {
                "id": restored.id,
                "type": restored.type.value,
                "ownerId": restored.owner_id,
                "name": restored.name,
                "version": restored.version,
            },
            # What the file said it held, so the interface can say what it just
            # did rather than only that it worked. Taken from the manifest read
            # before the restore, which is the same thing that was written.
            "counts": manifest.get("counts", {}),
            # Where the archive came from. Usually the same library; it need not
            # be, and somebody who has just restored a group into their personal
            # library should be told so rather than left to find out.
            "source": {
                "type": manifest["library"].get("type", ""),
                "ownerId": manifest["library"].get("id"),
                "name": manifest.get("name", ""),
            },
        }
    )
