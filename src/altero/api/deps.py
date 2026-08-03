"""FastAPI dependencies.

These adapt HTTP requests to the service layer: they pull credentials and path
parameters out of the request and hand plain values to :mod:`altero.services`.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from altero.errors import NotFoundError
from altero.models import ApiKey, Library, LibraryType
from altero.services import auth, keyusage

#: Header carrying the API key, as documented for the v3 API.
API_KEY_HEADER = "Zotero-API-Key"

#: Query parameter carrying the API key. Deprecated, but still supported.
API_KEY_PARAM = "key"


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session bound to the running application."""
    async for session in request.app.state.database.session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_credential(request: Request) -> str | None:
    """Return the API key supplied with the request, by any of the three means."""
    if credential := request.headers.get(API_KEY_HEADER):
        return credential

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()

    return request.query_params.get(API_KEY_PARAM)


async def get_api_key(request: Request, session: SessionDep) -> ApiKey | None:
    """Return the authenticated API key, or ``None`` for an anonymous request."""
    api_key = await auth.authenticate(session, get_credential(request))
    if api_key is not None:
        await _record_use(request, api_key)
    return api_key


async def _record_use(request: Request, api_key: ApiKey) -> None:
    """Note when and where this key was used, for the key list to show.

    In a session of its own. Sharing the request's would commit whatever it has
    open, which on a write path is a transaction holding a row lock on the
    library -- the one thing in this application that must not be broken up.
    """
    async with request.app.state.database.session_factory() as bookkeeping:
        await keyusage.record(
            bookkeeping,
            api_key.id,
            address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


ApiKeyDep = Annotated[ApiKey | None, Depends(get_api_key)]


async def get_library(request: Request, session: SessionDep) -> Library:
    """Return the library addressed by the route's ``/users`` or ``/groups`` prefix."""
    path_params = request.path_params
    if "user_id" in path_params:
        library_type, owner_id = LibraryType.USER, path_params["user_id"]
    elif "group_id" in path_params:
        library_type, owner_id = LibraryType.GROUP, path_params["group_id"]
    else:  # pragma: no cover - a route without a library prefix must not use this
        raise NotFoundError("Not found")

    return await auth.get_library(session, library_type, int(owner_id))


LibraryDep = Annotated[Library, Depends(get_library)]


async def get_readable_library(
    library: LibraryDep, api_key: ApiKeyDep, session: SessionDep
) -> Library:
    """Return the addressed library, requiring read access to it."""
    await auth.require_read(session, library, api_key)
    return library


ReadableLibraryDep = Annotated[Library, Depends(get_readable_library)]


async def get_writable_library(
    library: LibraryDep, api_key: ApiKeyDep, session: SessionDep
) -> Library:
    """Return the addressed library, requiring write access to it."""
    await auth.require_write(session, library, api_key)
    return library


WritableLibraryDep = Annotated[Library, Depends(get_writable_library)]


def get_base_url(request: Request) -> str:
    """Return the scheme and authority the request arrived on, without a trailing slash."""
    return str(request.base_url).rstrip("/")


BaseUrlDep = Annotated[str, Depends(get_base_url)]
