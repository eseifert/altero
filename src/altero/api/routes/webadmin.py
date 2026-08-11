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

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero import API_VERSION, __version__
from altero.api.deps import SessionDep
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.models import User
from altero.services import health, instancesettings, retention, storagestats

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


def _settings_payload(values: dict[str, int], defaults: dict[str, int]) -> dict:
    """Report the settings in force, and what the deployment would give.

    Both, because a number on the screen means two different things depending
    on where it came from: an operator who set 30 days in `config.py` and one
    who typed it into this screen have made the same policy, and only the
    second survives a change to the file.
    """
    return {
        "settings": values,
        "defaults": defaults,
        "limits": {
            name: {"maximum": definition.maximum, "zero": definition.zero}
            for name, definition in instancesettings.DEFINITIONS.items()
        },
    }


@router.get("/settings")
async def read_settings(
    request: Request, session: SessionDep, _admin: AdministratorDep
) -> Response:
    """Report the retention periods in force."""
    settings = request.app.state.settings
    return JSONResponse(
        _settings_payload(
            await instancesettings.read_all(session, settings),
            {
                name: instancesettings.default(settings, name)
                for name in instancesettings.DEFINITIONS
            },
        )
    )


@router.put("/settings")
async def write_settings(
    request: Request,
    session: SessionDep,
    _admin: AdministratorDep,
    body: Annotated[dict[str, Any], Body()],
    _csrf: CsrfDep,
) -> Response:
    """Change one or more retention periods.

    No password, unlike the account's own screens: this changes a policy rather
    than a credential, and nothing here can be used to become somebody else.
    What it can do is delete things later on, which is why the periods are
    validated rather than stored as typed — see
    :mod:`altero.services.instancesettings`.
    """
    settings = request.app.state.settings
    values = await instancesettings.save(session, settings, body)
    return JSONResponse(
        _settings_payload(
            values,
            {
                name: instancesettings.default(settings, name)
                for name in instancesettings.DEFINITIONS
            },
        )
    )


@router.post("/retention/run")
async def run_retention(
    request: Request,
    session: SessionDep,
    _admin: AdministratorDep,
    _csrf: CsrfDep,
    preview: bool = False,
) -> Response:
    """Apply the retention periods now, or report what they would do.

    Here as well as on a timer because an operator setting a period for the
    first time wants to see what it will take before it takes it, and because
    an instance whose `retention_interval` is zero — the default — has nothing
    else that would ever run it.
    """
    values = await instancesettings.read_all(session, request.app.state.settings)
    report = await retention.sweep(session, values, dry_run=preview)

    return JSONResponse(
        {
            "preview": preview,
            "itemsDeleted": report.items_deleted,
            "libraries": report.libraries,
            "activity": report.activity,
            "uploads": report.uploads,
            "sessions": report.sessions,
            "verifications": report.verifications,
            "invitations": report.invitations,
            "summary": retention.describe(report),
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
