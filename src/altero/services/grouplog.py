"""Reading back what happened in a group library.

The rows are the ones :mod:`altero.services.groupactivity` writes and
:mod:`altero.services.groupdigest` stamps rather than deletes, so one record
answers two questions: what to tell people, and what happened. Nothing here
writes.

What it is not is a per-object history. A row is one write request, which is
one library version, and it says who and how many -- not which items. Recording
which would mean a row per object per change, for a question people mostly do
not ask; what they ask is whether anything has happened lately, and by whom.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import GroupActivity, Library, User

#: Entries in a page when the caller does not say. A panel, not an archive.
DEFAULT_LIMIT = 50

#: Most a caller may ask for at once.
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Entry:
    """One thing that happened, with the account behind it if there was one."""

    id: int
    kind: str
    count: int
    when: datetime
    actor: User | None


@dataclass(frozen=True, slots=True)
class Page:
    entries: list[Entry]
    total: int


async def read(
    session: AsyncSession,
    library: Library,
    *,
    limit: int = DEFAULT_LIMIT,
    start: int = 0,
) -> Page:
    """Return a page of ``library``'s activity, newest first.

    Delivered and undelivered entries alike: the log is the record rather than
    the outbox, and something nobody had subscribed to still happened.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    start = max(0, start)

    total = (
        await session.scalar(
            select(func.count())
            .select_from(GroupActivity)
            .where(GroupActivity.library_id == library.id)
        )
    ) or 0

    rows = list(
        await session.scalars(
            select(GroupActivity)
            .where(GroupActivity.library_id == library.id)
            # The id breaks ties: several rows of one request share a timestamp
            # to the second, and without it a page boundary could repeat or
            # skip one.
            .order_by(GroupActivity.created.desc(), GroupActivity.id.desc())
            .offset(start)
            .limit(limit)
        )
    )

    actors = await _actors(session, rows)
    return Page(
        entries=[
            Entry(
                id=row.id,
                kind=row.kind,
                count=row.count,
                when=row.created,
                actor=actors.get(row.actor_id) if row.actor_id else None,
            )
            for row in rows
        ],
        total=total,
    )


async def _actors(session: AsyncSession, rows: list[GroupActivity]) -> dict[int, User]:
    """Resolve a page's accounts in one query.

    An id with no account behind it simply does not resolve, and the entry
    reads as having no actor -- which is also what a write that arrived without
    a key naming somebody looks like. Both are true statements about a change
    nobody can be named for.
    """
    wanted = {row.actor_id for row in rows if row.actor_id is not None}
    if not wanted:
        return {}

    found = await session.scalars(select(User).where(User.id.in_(wanted)))
    return {user.id: user for user in found}
