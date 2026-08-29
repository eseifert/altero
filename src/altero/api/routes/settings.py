"""Library settings.

The client keeps tag colours, feeds and similar preferences here, and syncs them
alongside items, so a library is not fully in step without them.
"""

from typing import Any

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import AccessDep, ReadableLibraryDep, SessionDep, WritableLibraryDep
from altero.api.responses import library_headers, not_modified
from altero.errors import InvalidInputError, RequestTooLargeError
from altero.services import settings as settings_service
from altero.services import writes

router = APIRouter(tags=["settings"])


@router.get("/users/{user_id}/settings")
@router.get("/groups/{group_id}/settings")
async def list_settings(
    request: Request, session: SessionDep, library: ReadableLibraryDep, access: AccessDep
) -> Response:
    """Return every setting, keyed by name."""
    if (response := not_modified(request, library.version)) is not None:
        return response

    since = request.query_params.get("since")
    stored = await settings_service.list_settings(session, library, int(since or 0), permit=access)

    return JSONResponse(
        settings_service.render_all(stored), headers=library_headers(library.version)
    )


@router.get("/users/{user_id}/settings/{name}")
@router.get("/groups/{group_id}/settings/{name}")
async def get_setting(
    name: str, session: SessionDep, library: ReadableLibraryDep, access: AccessDep
) -> Response:
    """Return one setting."""
    setting = await settings_service.get_setting(session, library, name, permit=access)
    return JSONResponse(settings_service.render(setting), headers=library_headers(library.version))


@router.post("/users/{user_id}/settings")
@router.post("/groups/{group_id}/settings")
async def replace_settings(
    request: Request, session: SessionDep, library: WritableLibraryDep, access: AccessDep
) -> Response:
    """Store a batch of settings, given as an object keyed by name."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise InvalidInputError("Uploaded data must be a JSON object")

    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=False)

    version = await writes.bump_library_version(session, library)
    for name, value in payload.items():
        await settings_service.save_setting(session, library, name, value, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.put("/users/{user_id}/settings/{name}")
@router.put("/groups/{group_id}/settings/{name}")
async def replace_setting(
    name: str, request: Request, session: SessionDep, library: WritableLibraryDep, access: AccessDep
) -> Response:
    """Store one setting."""
    payload: Any = await request.json()

    library = await writes.lock_library(session, library)
    header_version = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    if isinstance(payload, dict) and header_version is not None:
        payload = {"version": header_version, **payload}

    version = await writes.bump_library_version(session, library)
    await settings_service.save_setting(session, library, name, payload, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/settings/{name}")
@router.delete("/groups/{group_id}/settings/{name}")
async def delete_setting(
    name: str, request: Request, session: SessionDep, library: WritableLibraryDep, access: AccessDep
) -> Response:
    """Remove one setting."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    # ``permit`` reaches this lookup for the reason it reaches the tag rename's:
    # a confined credential sees no settings at all, so every name must answer
    # 404 rather than 404 for an absent one and 403 for a stored one.
    await settings_service.get_setting(session, library, name, permit=access)
    version = await writes.bump_library_version(session, library)
    await settings_service.delete_settings(session, library, [name], version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/users/{user_id}/settings")
@router.delete("/groups/{group_id}/settings")
async def delete_settings(
    request: Request, session: SessionDep, library: WritableLibraryDep, access: AccessDep
) -> Response:
    """Remove up to fifty settings named by ``settingKey``."""
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=True)

    names = [n for n in (request.query_params.get("settingKey") or "").split(",") if n]
    if not names:
        raise InvalidInputError("settingKey parameter not provided")
    if len(names) > writes.MAX_OBJECTS:
        raise RequestTooLargeError(
            f"Cannot delete more than {writes.MAX_OBJECTS} settings at a time"
        )

    version = await writes.bump_library_version(session, library)
    await settings_service.delete_settings(session, library, names, version, permit=access)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
