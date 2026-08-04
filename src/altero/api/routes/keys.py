"""Endpoints describing API keys and group membership."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from altero import serializers
from altero.api.deps import ApiKeyDep, BaseUrlDep, LibraryDep, SessionDep
from altero.api.responses import object_response
from altero.api.spa import MOUNT_PATH, is_built
from altero.errors import ForbiddenError, NotFoundError
from altero.models import ApiKey, Library
from altero.services import auth, groups
from altero.services import login as login_service

router = APIRouter(tags=["keys"])


async def _key_payload(session: AsyncSession, api_key: ApiKey) -> dict[str, Any]:
    """Render a key and the access it grants."""
    user = await auth.get_user(session, api_key.user_id)

    # Per-group overrides are stored against the internal library id, but the
    # response identifies groups by the id that appears in URLs.
    overrides: dict[int, dict[str, bool]] = {}
    for entry in await auth.list_group_overrides(session, api_key):
        library = await session.get(Library, entry.library_id)
        if library is not None:
            overrides[library.owner_id] = {"library": entry.read, "write": entry.write}

    return serializers.api_key(api_key, user, overrides)


@router.get("/keys/current")
async def get_current_key(session: SessionDep, api_key: ApiKeyDep) -> dict[str, Any]:
    """Return the access granted by the key the request was made with.

    This is the first thing the desktop client asks for after storing a key.
    """
    if api_key is None:
        raise ForbiddenError("Invalid key")
    return await _key_payload(session, api_key)


@router.delete("/keys/current", status_code=204)
async def delete_current_key(session: SessionDep, api_key: ApiKeyDep) -> Response:
    """Revoke the key the request was made with, unlinking the client."""
    if api_key is None:
        raise ForbiddenError("Invalid key")

    await session.delete(api_key)
    await session.commit()
    return Response(status_code=204)


@router.post("/keys/sessions", status_code=201)
async def start_login_session(
    request: Request, session: SessionDep, base_url: BaseUrlDep
) -> JSONResponse:
    """Begin a login, returning a token to poll and a page to send the user to.

    Upstream authenticates the user in a browser against zotero.org. altero has
    no web interface and stores no passwords, so the page it returns explains
    how to approve the login from the command line instead.
    """
    body: dict[str, Any] = {}
    if await request.body():
        body = await request.json()

    user_id = body.get("userID") if isinstance(body, dict) else None
    login = await login_service.start_session(
        session, int(user_id) if user_id is not None else None
    )

    return JSONResponse(
        {
            "sessionToken": login.token,
            "loginURL": f"{base_url}/keys/sessions/{login.token}/login",
        },
        status_code=201,
    )


@router.get("/keys/sessions/{token}/login")
async def login_session_page(token: str, session: SessionDep) -> Response:
    """Send the user where the login can be approved.

    The client opens this in a browser. With the web interface built that is
    the confirmation screen; without it there is nowhere to send them, so the
    command line instructions stand -- the API is fully usable in that state
    and a redirect to a 503 would be worse than a sentence they can act on.
    """
    await login_service.get_session(session, token)

    if is_built():
        return RedirectResponse(f"{MOUNT_PATH}/link?token={token}", status_code=303)

    return PlainTextResponse(
        "Approve this login from the command line on the server:\n\n"
        f"    altero login approve {token} <username>\n\n"
        "The client is waiting and will continue once you have.\n"
    )


@router.get("/keys/sessions/{token}")
async def poll_login_session(token: str, session: SessionDep) -> JSONResponse:
    """Report whether a login has been approved yet."""
    try:
        login = await login_service.get_session(session, token)
    except login_service.SessionExpiredError as error:
        # The client distinguishes an expired session from a missing one.
        return JSONResponse({"error": error.message}, status_code=410)

    return JSONResponse(await login_service.render(session, login))


@router.delete("/keys/sessions/{token}", status_code=204)
async def cancel_login_session(token: str, session: SessionDep) -> Response:
    """Abandon a login the user backed out of."""
    await login_service.cancel_session(session, token)
    return Response(status_code=204)


@router.get("/keys/{key}")
async def get_key(key: str, session: SessionDep, api_key: ApiKeyDep) -> dict[str, Any]:
    """Return the access granted by an API key.

    A key may only be inspected by a request authenticated with that same key.
    """
    if api_key is None or api_key.key != key:
        raise ForbiddenError("Forbidden")

    return await _key_payload(session, api_key)


@router.get("/groups/{group_id}")
async def get_group(
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> Response:
    """Return one group's metadata.

    Readable by anyone who may read the library, which for a public group is
    anyone at all. A group the caller may not read answers 404 rather than 403,
    which is what upstream's `canAccess` check does: a stranger learns nothing
    about which private groups exist.
    """
    try:
        await auth.require_read(session, library, api_key)
    except ForbiddenError:
        raise NotFoundError("Group not found") from None

    group = await groups.get_group(session, library)
    return object_response(serializers.group(library, group, base_url), library.version)


@router.get("/users/{user_id}/groups")
async def list_user_groups(
    user_id: int,
    session: SessionDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> list[dict[str, Any]]:
    """Return the groups a user belongs to.

    Only the user themselves may list their groups.
    """
    if api_key is None or api_key.user_id != user_id:
        raise ForbiddenError("Forbidden")

    await auth.get_user(session, user_id)
    memberships = await groups.list_groups_for_user(session, user_id)

    return [serializers.group(library, group, base_url) for library, group in memberships]
