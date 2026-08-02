"""Provisioning of users, libraries, API keys and groups.

These back the command line rather than any endpoint: the Web API has no way to
create an account or issue a credential, so without them a deployment could only
be set up by writing rows by hand.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.keys import generate_api_key
from altero.models import ApiKey, Group, GroupMember, Library, LibraryType, User


async def _next_user_id(session: AsyncSession) -> int:
    """Return an unused user id.

    Ids are assigned here rather than by the database because they appear in
    URLs and must survive a restore into an empty table.
    """
    highest = await session.scalar(select(func.max(User.id)))
    return (highest or 0) + 1


async def get_user_by_name(session: AsyncSession, username: str) -> User:
    """Return the named user."""
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        raise NotFoundError(f"No user named '{username}'")
    return user


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    display_name: str = "",
    user_id: int | None = None,
) -> User:
    """Create a user and the personal library that belongs to them."""
    if not username:
        raise InvalidInputError("A username is required")

    existing = await session.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise InvalidInputError(f"A user named '{username}' already exists")

    user = User(
        id=user_id if user_id is not None else await _next_user_id(session),
        username=username,
        display_name=display_name,
    )
    session.add(user)
    await session.flush()

    session.add(
        Library(
            type=LibraryType.USER,
            owner_id=user.id,
            name=display_name or username,
            version=0,
        )
    )
    await session.commit()
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list(await session.scalars(select(User).order_by(User.id)))


async def create_api_key(
    session: AsyncSession,
    *,
    username: str,
    name: str,
    read: bool = True,
    write: bool = True,
    notes: bool = True,
    files: bool = True,
    all_groups_read: bool = False,
    all_groups_write: bool = False,
) -> ApiKey:
    """Issue an API key for a user and return it.

    The key itself is only available here; nothing later can recover it, so the
    caller is responsible for showing it once.
    """
    user = await get_user_by_name(session, username)

    api_key = ApiKey(
        key=generate_api_key(),
        user_id=user.id,
        name=name,
        library_read=read,
        library_write=write,
        notes_read=notes,
        files_read=files,
        all_groups_read=all_groups_read,
        all_groups_write=all_groups_write,
    )
    session.add(api_key)
    await session.commit()
    return api_key


async def list_api_keys(session: AsyncSession) -> list[ApiKey]:
    return list(await session.scalars(select(ApiKey).order_by(ApiKey.id)))


async def revoke_api_key(session: AsyncSession, key: str) -> None:
    """Delete an API key so that it stops working immediately."""
    api_key = await session.scalar(select(ApiKey).where(ApiKey.key == key))
    if api_key is None:
        raise NotFoundError("No such key")
    await session.delete(api_key)
    await session.commit()


async def _next_group_id(session: AsyncSession) -> int:
    highest = await session.scalar(
        select(func.max(Library.owner_id)).where(Library.type == LibraryType.GROUP)
    )
    return (highest or 0) + 1


async def create_group(
    session: AsyncSession,
    *,
    name: str,
    owner_username: str,
    group_id: int | None = None,
    public: bool = False,
) -> Library:
    """Create a group library owned by a user, who becomes its first admin."""
    if not name:
        raise InvalidInputError("A group name is required")

    owner = await get_user_by_name(session, owner_username)

    library = Library(
        type=LibraryType.GROUP,
        owner_id=group_id if group_id is not None else await _next_group_id(session),
        name=name,
        version=0,
        public=public,
    )
    session.add(library)
    await session.flush()

    session.add(
        Group(
            library_id=library.id,
            owner_id=owner.id,
            name=name,
            type="PublicOpen" if public else "Private",
        )
    )
    session.add(GroupMember(library_id=library.id, user_id=owner.id, role="admin"))
    await session.commit()
    return library


async def add_group_member(
    session: AsyncSession,
    library: Library,
    *,
    username: str,
    role: str = "member",
) -> GroupMember:
    """Add a user to a group library."""
    user = await get_user_by_name(session, username)

    existing = await session.scalar(
        select(GroupMember).where(
            GroupMember.library_id == library.id, GroupMember.user_id == user.id
        )
    )
    if existing is not None:
        raise InvalidInputError(f"'{username}' is already a member")

    member = GroupMember(library_id=library.id, user_id=user.id, role=role)
    session.add(member)
    await session.commit()
    return member


async def list_group_members(session: AsyncSession, library: Library) -> list[GroupMember]:
    return list(
        await session.scalars(
            select(GroupMember)
            .where(GroupMember.library_id == library.id)
            .order_by(GroupMember.user_id)
        )
    )


async def list_libraries(session: AsyncSession) -> list[Library]:
    return list(await session.scalars(select(Library).order_by(Library.id)))


async def set_library_version(
    session: AsyncSession,
    *,
    library_type: LibraryType,
    owner_id: int,
    version: int,
) -> Library:
    """Raise a library's version counter to ``version``.

    A library recreated from an empty database starts counting at zero again,
    while clients that synced against the original still hold the version they
    last saw. The desktop application refuses to move its stored version
    backwards -- during an ordinary sync and during "restore to server" alike --
    so it can neither upload nor be reset out of the state. Lifting the counter
    back over what the clients remember is the only way to reach them again.

    Which is also why the version may only ever go up: lowering one is how a
    working deployment locks itself out.
    """
    if version < 0:
        raise InvalidInputError("A library version cannot be negative")

    library = await session.scalar(
        select(Library).where(Library.type == library_type, Library.owner_id == owner_id)
    )
    if library is None:
        raise NotFoundError(f"No {library_type.value} library with id {owner_id}")

    if version < library.version:
        raise InvalidInputError(
            f"A library version cannot be lowered (it is {library.version}); "
            "clients that have seen it would stop syncing"
        )

    library.version = version
    await session.commit()
    return library
