"""Authentication, library lookup and access control.

This module deliberately knows nothing about HTTP: callers pass a credential
string that they extracted however they like, and get back domain objects or a
domain error.

Permission resolution is split in two. :func:`access_for` is a pure function of
values already in hand, so the rules can be read and tested on their own;
:func:`get_access` is the async wrapper that fetches the per-group override it
needs. Nothing here relies on lazy relationship loading, which would otherwise
fail whenever a key reached the check without having been loaded by a query.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, NotFoundError
from altero.models import ApiKey, ApiKeyGroupAccess, Library, LibraryType, User


@dataclass(frozen=True, slots=True)
class Access:
    """The access a credential has to one library."""

    read: bool
    write: bool


async def authenticate(session: AsyncSession, credential: str | None) -> ApiKey | None:
    """Return the API key identified by ``credential``.

    Returns ``None`` when no credential was supplied. An unrecognised credential
    is an error rather than anonymous access, so that a typo in a key is not
    silently downgraded to a public-library request.
    """
    if not credential:
        return None

    api_key = await session.scalar(select(ApiKey).where(ApiKey.key == credential))
    if api_key is None:
        raise ForbiddenError("Invalid key")
    return api_key


async def get_library(
    session: AsyncSession,
    library_type: LibraryType,
    owner_id: int,
) -> Library:
    """Return the library addressed by a ``/users/<id>`` or ``/groups/<id>`` prefix."""
    library = await session.scalar(
        select(Library).where(Library.type == library_type, Library.owner_id == owner_id)
    )
    if library is None:
        raise NotFoundError("Not found")
    return library


def access_for(
    library: Library,
    api_key: ApiKey | None,
    override: ApiKeyGroupAccess | None = None,
) -> Access:
    """Return the access ``api_key`` has to ``library``.

    A public library is readable by anyone, including unauthenticated callers.
    Write access always implies read access, so a key that may write but not read
    can do neither.

    Args:
        override: The key's per-group access for this library, if any. Only
            meaningful for group libraries.
    """
    if api_key is None:
        return Access(read=library.public, write=False)

    if library.type is LibraryType.USER:
        # A key only ever grants write access to its own owner's library. Another
        # user's library is reachable only if it is public, and then read-only.
        if library.owner_id != api_key.user_id:
            return Access(read=library.public, write=False)
        return Access(
            read=api_key.library_read,
            write=api_key.library_read and api_key.library_write,
        )

    if override is not None:
        read, write = override.read, override.write
    else:
        read, write = api_key.all_groups_read, api_key.all_groups_write

    return Access(read=read or library.public, write=read and write)


async def get_group_override(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> ApiKeyGroupAccess | None:
    """Return the key's per-group access for ``library``, if one is recorded."""
    if api_key is None or library.type is not LibraryType.GROUP:
        return None

    return await session.scalar(
        select(ApiKeyGroupAccess).where(
            ApiKeyGroupAccess.api_key_id == api_key.id,
            ApiKeyGroupAccess.library_id == library.id,
        )
    )


async def get_access(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> Access:
    """Return the access ``api_key`` has to ``library``, fetching any override."""
    override = await get_group_override(session, library, api_key)
    return access_for(library, api_key, override)


async def require_read(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> None:
    """Raise :class:`ForbiddenError` unless ``api_key`` may read ``library``."""
    if not (await get_access(session, library, api_key)).read:
        raise ForbiddenError("Forbidden")


async def require_write(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> None:
    """Raise :class:`ForbiddenError` unless ``api_key`` may write to ``library``."""
    if not (await get_access(session, library, api_key)).write:
        raise ForbiddenError("Forbidden")


async def get_user(session: AsyncSession, user_id: int) -> User:
    """Return the user with ``user_id``."""
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("Not found")
    return user


async def get_api_key_by_value(session: AsyncSession, key: str) -> ApiKey:
    """Return the API key with this key string."""
    api_key = await session.scalar(select(ApiKey).where(ApiKey.key == key))
    if api_key is None:
        raise NotFoundError("No such key")
    return api_key


async def list_group_overrides(
    session: AsyncSession,
    api_key: ApiKey,
) -> list[ApiKeyGroupAccess]:
    """Return every per-group access recorded for ``api_key``."""
    result = await session.scalars(
        select(ApiKeyGroupAccess).where(ApiKeyGroupAccess.api_key_id == api_key.id)
    )
    return list(result)
