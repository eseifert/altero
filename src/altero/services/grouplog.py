"""Reading back what happened in a group library.

The rows are the ones :mod:`altero.services.groupactivity` writes and
:mod:`altero.services.groupdigest` stamps rather than deletes, so one record
answers two questions: what to tell people, and what happened. Nothing here
writes.

An entry is one write request -- which is one library version -- so it says who
changed how many objects, and names them: `dataserver#89` asks for "what was
modified", and a count alone does not answer that.

The names are snapshots taken when the change happened, not joins onto the
objects now. An item renamed afterwards must not rewrite the history of what it
used to be called, and a deleted one has nothing left to join to at all --
which is the entry most worth being able to read.

What an entry does not carry is what *about* an object changed. Knowing that a
title went from one string to another would mean storing both, for every field
of every write, which is a different feature with a very different cost.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from altero.models import GroupActivity, Library, User

#: Entries in a page when the caller does not say. A panel, not an archive.
DEFAULT_LIMIT = 50

#: Most a caller may ask for at once.
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Touched:
    """One object a change touched, named as it was at the time."""

    key: str
    name: str


@dataclass(frozen=True, slots=True)
class Entry:
    """One thing that happened, with the account behind it if there was one."""

    id: int
    kind: str
    count: int
    when: datetime
    actor: User | None
    #: What was touched. Empty for anything recorded before objects were kept,
    #: which is everything in an instance that upgraded into this -- ``count``
    #: still says how much, so the entry stays meaningful.
    objects: list[Touched]


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
            # Asked for explicitly: the relationship does not load itself, so
            # the sweep that never reads it never pays for it.
            .options(selectinload(GroupActivity.objects))
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
                # Loaded with the row, so a page costs one further query and
                # not one per entry.
                objects=[
                    Touched(key=touched.object_key, name=touched.name)
                    for touched in sorted(row.objects, key=lambda touched: touched.id)
                ],
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
