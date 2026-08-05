"""Recording what happened in a group library.

The write path calls :func:`record`; the sweep in
:mod:`altero.services.groupdigest` picks the rows up once they have settled and
turns them into notifications and mail. Keeping those apart is what stops a
group's size from being a cost on the sync path: a request writes one row
whether the group has two members or fifty.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ActivityKind, GroupActivity, Library, LibraryType


async def record(
    session: AsyncSession,
    library: Library,
    *,
    actor_id: int | None,
    kind: ActivityKind,
    count: int,
) -> GroupActivity | None:
    """Note that ``count`` objects of ``kind`` changed in ``library``.

    Does nothing, and returns ``None``, for a library nobody else can see or a
    request that changed nothing. Both are cheap enough to check here that no
    caller has to remember to.

    Not committed: this belongs to the transaction the write is already in, so
    a request that rolls back records no activity for a change that never
    happened.
    """
    if library.type is not LibraryType.GROUP or count <= 0:
        return None

    activity = GroupActivity(
        library_id=library.id,
        actor_id=actor_id,
        kind=kind,
        count=count,
    )
    session.add(activity)
    await session.flush()
    return activity
