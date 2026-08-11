"""The operator's view of the instance.

Everything here is under ``/web/admin``, authenticates with the same cookie as
the rest of ``/web``, and is refused to anybody who does not administer the
instance. Nothing here is reachable with an API key: an instance administrator
is not a Zotero concept, and putting one in the v3 API would extend the API
where compatibility wins — see ``docs/compatibility.md``.

**An administrator counts and measures; they do not read.** No route here
answers with an item, a title, a tag, a note or a file, and the flag adds
nothing to :func:`altero.services.auth.user_access`: somebody administering the
instance has exactly the access to a library they had before. What they get is
what the instance costs, what state it is in, and the levers that belong to the
operator rather than to a library — which is the gap ``docs/motivation.md``
names, and which until now meant a shell on the server.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero import API_VERSION, __version__
from altero.api.deps import SessionDep
from altero.api.routes.web import CurrentUserDep
from altero.models import User
from altero.services import health, storagestats

router = APIRouter(prefix="/web/admin", tags=["web"])


async def get_administrator(user: CurrentUserDep) -> User:
    """Return the signed-in account, or refuse unless it administers this instance.

    403 rather than 404: the account is signed in and the screen exists, it is
    simply not theirs. Pretending otherwise would tell somebody who went
    looking that they had found a bug rather than a boundary.
    """
    if not user.administrator:
        raise HTTPException(status_code=403, detail="Only an administrator of this instance")
    return user


AdministratorDep = Annotated[User, Depends(get_administrator)]


def _library_usage(entry: storagestats.LibraryUsage) -> dict:
    """Render one library's usage. Numbers and a name, never its contents."""
    return {
        "id": entry.id,
        "type": entry.type.value,
        "ownerId": entry.owner_id,
        "name": entry.name,
        "version": entry.version,
        "items": entry.items,
        "trashed": entry.trashed,
        "collections": entry.collections,
        "tags": entry.tags,
        "attachments": entry.attachments,
        "files": entry.files,
        "bytes": entry.bytes,
        "missing": entry.missing,
    }


@router.get("/overview")
async def read_overview(
    request: Request, session: SessionDep, _admin: AdministratorDep
) -> Response:
    """Report what this instance is running and how much of everything it holds.

    The migration revision is here because "which migration is this instance
    on" is the question an upgrade asks, and reading it otherwise means a shell
    and `alembic current`. ``/health`` reports it too, and to anybody; this adds
    the counts, which are nobody else's business.

    The database is reported as its dialect and nothing more. The URL carries a
    password.
    """
    settings = request.app.state.settings
    usage = await storagestats.collect(session, settings.storage_path)

    return JSONResponse(
        {
            "version": __version__,
            "apiVersion": API_VERSION,
            "revision": await health.migration_revision(session),
            "database": settings.database_url.split("+")[0].split(":")[0],
            "users": usage.users,
            "libraries": len(usage.libraries),
            "groups": usage.groups,
            "storagePath": str(settings.storage_path),
            "nominalBytes": usage.nominal_bytes,
            "realBytes": usage.real_bytes,
            "savedBytes": usage.saved_bytes,
            "orphanBytes": usage.orphan_bytes,
            "orphanFiles": usage.orphan_files,
            "missingFiles": usage.missing_files,
        }
    )


@router.get("/storage")
async def read_storage(request: Request, session: SessionDep, _admin: AdministratorDep) -> Response:
    """Report what each library costs, and what does not add up.

    Nominal against real is the point of it: a file attached in two libraries
    is on disk once and in both libraries' accounts. See
    :mod:`altero.services.storagestats`.
    """
    usage = await storagestats.collect(session, request.app.state.settings.storage_path)

    return JSONResponse(
        {
            "libraries": [_library_usage(entry) for entry in usage.libraries],
            "nominalBytes": usage.nominal_bytes,
            "realBytes": usage.real_bytes,
            "savedBytes": usage.saved_bytes,
            "storedFiles": usage.stored_files,
            "storedBytes": usage.stored_bytes,
            "orphanFiles": usage.orphan_files,
            "orphanBytes": usage.orphan_bytes,
            "missingFiles": usage.missing_files,
        }
    )
