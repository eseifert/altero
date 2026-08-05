"""Recording what happened in a group library.

The write path calls :func:`record`; the sweep in
:mod:`altero.services.groupdigest` picks the rows up once they have settled and
turns them into notifications and mail. Keeping those apart is what stops a
group's size from being a cost on the sync path: a request writes one row
whether the group has two members or fifty.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import (
    ActivityKind,
    Collection,
    GroupActivity,
    GroupActivityObject,
    Item,
    Library,
    LibraryType,
)

#: An object a change touched: its key, and what it was called at the time.
Named = tuple[str, str]


async def name_items(session: AsyncSession, library: Library, keys: Sequence[str]) -> list[Named]:
    """Return ``keys`` with the name each item currently carries.

    Read from ``sort_title``, which :mod:`altero.services.itemdata` derives on
    every write and which already answers "what is this item called" for every
    item type -- including a note, which has no title and is shown by the start
    of its text. Deriving it a second time here would be a second answer to
    drift against the item list.
    """
    if not keys:
        return []

    found = await session.execute(
        select(Item.key, Item.sort_title).where(
            Item.library_id == library.id, Item.key.in_(list(keys))
        )
    )
    names = {key: title for key, title in found.all()}
    return [(key, names.get(key, "")) for key in keys if key in names]


async def name_collections(
    session: AsyncSession, library: Library, keys: Sequence[str]
) -> list[Named]:
    """Return ``keys`` with the name each collection currently carries."""
    if not keys:
        return []

    found = await session.execute(
        select(Collection.key, Collection.name).where(
            Collection.library_id == library.id, Collection.key.in_(list(keys))
        )
    )
    names = {key: name for key, name in found.all()}
    return [(key, names.get(key, "")) for key in keys if key in names]


async def record(
    session: AsyncSession,
    library: Library,
    *,
    actor_id: int | None,
    kind: ActivityKind,
    count: int,
    objects: Sequence[Named] = (),
) -> GroupActivity | None:
    """Note that ``count`` objects of ``kind`` changed in ``library``.

    Does nothing, and returns ``None``, for a library nobody else can see or a
    request that changed nothing. Both are cheap enough to check here that no
    caller has to remember to.

    Args:
        objects: The objects behind the change, as key and name. Resolved by
            the caller rather than here, because a deletion has to be named
            *before* the row goes and there would be nothing left to read.

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
    activity.objects = [
        GroupActivityObject(object_key=key, name=name or "") for key, name in objects
    ]
    session.add(activity)
    await session.flush()
    return activity
