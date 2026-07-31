"""Helpers that put objects into the database for a test to work against."""

from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ApiKey, Group, GroupMember, Library, LibraryType, User


async def make_user(
    session: AsyncSession,
    user_id: int = 1,
    username: str = "octocat",
    display_name: str = "Mona Lisa",
) -> User:
    """Create a user together with their personal library."""
    user = User(id=user_id, username=username, display_name=display_name)
    session.add(user)
    session.add(Library(type=LibraryType.USER, owner_id=user_id, name=display_name or username))
    await session.commit()
    return user


async def make_library(
    session: AsyncSession,
    *,
    library_type: LibraryType = LibraryType.USER,
    owner_id: int = 1,
    name: str = "",
    public: bool = False,
) -> Library:
    library = Library(type=library_type, owner_id=owner_id, name=name, public=public)
    session.add(library)
    await session.commit()
    return library


async def make_group(
    session: AsyncSession,
    *,
    group_id: int = 100,
    owner_id: int = 1,
    name: str = "Test Group",
    public: bool = False,
    members: dict[int, str] | None = None,
) -> Library:
    """Create a group library with its metadata and membership rows."""
    library = Library(type=LibraryType.GROUP, owner_id=group_id, name=name, public=public)
    session.add(library)
    await session.flush()

    session.add(Group(library_id=library.id, owner_id=owner_id, name=name))
    session.add(GroupMember(library_id=library.id, user_id=owner_id, role="admin"))
    for user_id, role in (members or {}).items():
        session.add(GroupMember(library_id=library.id, user_id=user_id, role=role))

    await session.commit()
    return library


async def make_api_key(
    session: AsyncSession,
    *,
    key: str = "P9NiFoyLeZu2bZNvvuQPDWsd",
    user_id: int = 1,
    name: str = "Test key",
    library_read: bool = True,
    library_write: bool = True,
    notes_read: bool = True,
    files_read: bool = True,
    all_groups_read: bool = False,
    all_groups_write: bool = False,
) -> ApiKey:
    api_key = ApiKey(
        key=key,
        user_id=user_id,
        name=name,
        library_read=library_read,
        library_write=library_write,
        notes_read=notes_read,
        files_read=files_read,
        all_groups_read=all_groups_read,
        all_groups_write=all_groups_write,
    )
    session.add(api_key)
    await session.commit()
    return api_key
