"""Group libraries."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Group, GroupMember, Library, LibraryType


async def get_group(session: AsyncSession, library: Library) -> Group:
    """Return the metadata of a group library.

    Raises:
        NotFoundError: The library is a group with no metadata row, which a
            correctly provisioned instance does not have.
    """
    group = await session.scalar(select(Group).where(Group.library_id == library.id))
    if group is None:
        raise NotFoundError("Group not found")
    return group


async def list_groups_for_user(
    session: AsyncSession,
    user_id: int,
) -> list[tuple[Library, Group]]:
    """Return the group libraries ``user_id`` belongs to, with their metadata."""
    statement = (
        select(Library, Group)
        .join(Group, Group.library_id == Library.id)
        .join(GroupMember, GroupMember.library_id == Library.id)
        .where(GroupMember.user_id == user_id, Library.type == LibraryType.GROUP)
        .order_by(Library.owner_id)
    )
    result = await session.execute(statement)
    return [(library, group) for library, group in result.all()]
