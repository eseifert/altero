"""What each member of a group has asked to hear about.

One flag per :class:`~altero.models.activity.ActivityKind` per membership. The
sweep in :mod:`altero.services.groupdigest` asks :func:`subscribers` who to
write to; nothing else needs to know how the answer is stored.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import ActivityKind, GroupMember, Library, User

#: The column each kind is held in. Explicit rather than derived from the enum
#: name, so renaming a kind in the API does not silently rename a column.
_COLUMNS: dict[ActivityKind, str] = {
    ActivityKind.ITEMS_CHANGED: "notify_items_changed",
    ActivityKind.ITEMS_DELETED: "notify_items_deleted",
    ActivityKind.MEMBERS_CHANGED: "notify_members_changed",
    ActivityKind.COLLECTIONS_CHANGED: "notify_collections_changed",
}


def kind_from_name(name: str) -> ActivityKind:
    """Return the kind ``name`` denotes.

    The boundary between a string off the wire and the enum everything else
    uses. The browser sends these names, so an unknown one is a client error
    rather than something to fall back from.
    """
    try:
        return ActivityKind(name)
    except ValueError:
        raise InvalidInputError(f"Unknown notification kind '{name}'") from None


def _column_for(kind: ActivityKind) -> str:
    column = _COLUMNS.get(kind)
    if column is None:  # pragma: no cover - every kind is mapped above
        raise InvalidInputError(f"Unknown notification kind '{kind}'")
    return column


async def _membership(session: AsyncSession, library: Library, user_id: int) -> GroupMember:
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.library_id == library.id, GroupMember.user_id == user_id
        )
    )
    if member is None:
        # Not found rather than forbidden: subscribing is not a way to learn
        # that a private group exists.
        raise NotFoundError("You are not a member of this group")
    return member


async def get(session: AsyncSession, library: Library, *, user_id: int) -> dict[ActivityKind, bool]:
    """Return every kind and whether this member wants it."""
    member = await _membership(session, library, user_id)
    return {kind: bool(getattr(member, column)) for kind, column in _COLUMNS.items()}


async def subscribed_kinds(
    session: AsyncSession, library: Library, *, user_id: int
) -> frozenset[ActivityKind]:
    """Return only the kinds this member wants."""
    wanted = await get(session, library, user_id=user_id)
    return frozenset(kind for kind, on in wanted.items() if on)


async def set_kind(
    session: AsyncSession,
    library: Library,
    *,
    user_id: int,
    kind: ActivityKind,
    wanted: bool,
) -> GroupMember:
    """Turn one kind on or off for one member.

    Not committed: the caller decides the transaction, so a request setting
    several kinds writes them together or not at all.
    """
    column = _column_for(kind)
    member = await _membership(session, library, user_id)
    setattr(member, column, wanted)
    await session.flush()
    return member


async def subscribers(session: AsyncSession, library: Library, kind: ActivityKind) -> list[User]:
    """Return the members who asked to hear about ``kind`` in ``library``.

    Joined against the membership rather than read from a stored recipient
    list, so somebody removed from the group stops being a recipient at once,
    with no separate step to forget.
    """
    column = getattr(GroupMember, _column_for(kind))
    result = await session.scalars(
        select(User)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.library_id == library.id, column.is_(True))
        .order_by(User.id)
    )
    return list(result)
