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

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, NotFoundError
from altero.models import (
    ApiKey,
    ApiKeyGroupAccess,
    Group,
    GroupMember,
    Library,
    LibraryType,
    User,
)


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
    membership: GroupMember | None = None,
    group: Group | None = None,
) -> Access:
    """Return the access ``api_key`` has to ``library``.

    A public library is readable by anyone, including unauthenticated callers.
    Write access always implies read access, so a key that may write but not read
    can do neither.

    For a group library three things have to agree, and all three are ceilings
    rather than grants: the key's group permissions, membership of the group,
    and the group's own policy. A key saying "all groups" means every group its
    owner belongs to -- not every group on the server, which is what it used to
    mean here and which let anyone holding such a key read every private
    library on the instance.

    Args:
        override: The key's per-group access for this library, if any. Only
            meaningful for group libraries.
        membership: The key owner's membership of this group, if any.
        group: The group's metadata, which says who may edit it.
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

    if membership is None:
        # A stranger to the group. A public one is still readable, because that
        # is what public means, and still not writable.
        return Access(read=library.public, write=False)

    if override is not None:
        read, write = override.read, override.write
    else:
        read, write = api_key.all_groups_read, api_key.all_groups_write

    # A group may reserve editing for its administrators. Reading is decided by
    # `library.public` together with the key, which is where `libraryReading`
    # has already been resolved to.
    if group is not None and group.library_editing == "admins" and membership.role != "admin":
        write = False

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


async def get_group_context(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> tuple[GroupMember | None, Group | None]:
    """Return the caller's membership of ``library`` and the group's policy.

    One query with an outer join rather than two, because this runs on every
    request addressed to a group library.
    """
    if api_key is None or library.type is not LibraryType.GROUP:
        return None, None

    row = (
        await session.execute(
            select(GroupMember, Group)
            .select_from(Group)
            .outerjoin(
                GroupMember,
                and_(
                    GroupMember.library_id == Group.library_id,
                    GroupMember.user_id == api_key.user_id,
                ),
            )
            .where(Group.library_id == library.id)
        )
    ).first()

    return (row[0], row[1]) if row is not None else (None, None)


async def get_access(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> Access:
    """Return the access ``api_key`` has to ``library``, fetching what it needs."""
    override = await get_group_override(session, library, api_key)
    membership, group = await get_group_context(session, library, api_key)
    return access_for(library, api_key, override, membership, group)


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


async def require_file_write(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> None:
    """Raise unless ``api_key`` may put files in ``library``.

    A group carries a ``fileEditing`` policy of its own, separate from who may
    edit the library: a group can let every member add items and still keep the
    attachments -- which is where the disk goes -- to its administrators, or
    forbid them outright. A personal library has no such distinction.
    """
    await require_write(session, library, api_key)

    membership, group = await get_group_context(session, library, api_key)
    if group is None or membership is None:
        return

    if group.file_editing == "none":
        raise ForbiddenError("This group does not allow file uploads")
    if group.file_editing == "admins" and membership.role != "admin":
        raise ForbiddenError("Only an administrator of this group can upload files")


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
