"""Group libraries."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Group, GroupMember, Library, LibraryType


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
