"""Turning settled group activity into one notification and one message.

This is what makes the feature a digest rather than a stream. A client syncing
a library uploads in batches of fifty, so a member who asked to hear about new
items would be told ten times about one sync. Activity is therefore left where
:mod:`altero.services.groupactivity` put it until the library has been quiet
for a while, and then everything waiting is rendered together.

The fan-out to recipients happens here rather than on the write path. A group
with fifty members costs one row when somebody writes and fifty notifications
once, later, off anybody's request.

Nothing here raises. A digest is *about* something that has already happened,
so a relay that will not take the message must not cause the activity to be
delivered twice on the next sweep, and must not take down whatever else the
sweep was doing.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ActivityKind, GroupActivity, Library, User
from altero.services import groupprefs, notifications
from altero.services.mail import Message

logger = logging.getLogger("altero.groupdigest")

#: How long a library must be quiet before what happened in it is sent.
DEFAULT_QUIET_PERIOD = timedelta(minutes=15)

#: Sends one message and says whether a relay took it.
Notify = Callable[[Message], Awaitable[bool]]

#: What each kind is called in a digest. One line per kind, in this order, so
#: two digests about the same group read the same way.
_LINES: dict[ActivityKind, tuple[str, str]] = {
    ActivityKind.ITEMS_CHANGED: (
        "{count} item was added or changed",
        "{count} items were added or changed",
    ),
    ActivityKind.ITEMS_DELETED: ("{count} item was deleted", "{count} items were deleted"),
    ActivityKind.MEMBERS_CHANGED: ("{count} membership changed", "{count} memberships changed"),
    ActivityKind.COLLECTIONS_CHANGED: (
        "{count} collection was added or changed",
        "{count} collections were added or changed",
    ),
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _describe(counts: dict[ActivityKind, int]) -> list[str]:
    """Return one line per kind that happened, in a fixed order."""
    lines = []
    for kind, (singular, plural) in _LINES.items():
        count = counts.get(kind, 0)
        if count:
            lines.append((singular if count == 1 else plural).format(count=count))
    return lines


async def _settled_libraries(session: AsyncSession, quiet_period: timedelta) -> list[int]:
    """Return the libraries whose waiting activity has stopped arriving.

    Judged by the *newest* waiting row rather than the oldest: a sync still
    running is one event that has not finished happening, and reporting its
    first half would mean reporting the second half separately.
    """
    cutoff = _now() - quiet_period
    result = await session.execute(
        select(GroupActivity.library_id)
        .where(GroupActivity.flushed.is_(None))
        .group_by(GroupActivity.library_id)
        .having(func.max(GroupActivity.created) <= cutoff)
    )
    return [library_id for (library_id,) in result.all()]


async def _claim(session: AsyncSession, library_id: int) -> list[GroupActivity]:
    """Take the waiting rows for one library, so no other sweep sends them.

    The stamp is the claim: two sweeps racing -- two workers, or one that ran
    long -- cannot both match ``flushed IS NULL``, so only one of them gets a
    non-empty answer and only one digest goes out.
    """
    claimed_at = _now()
    result = await session.execute(
        update(GroupActivity)
        .where(GroupActivity.library_id == library_id, GroupActivity.flushed.is_(None))
        .values(flushed=claimed_at)
        .returning(GroupActivity.id)
    )
    ids = [row_id for (row_id,) in result.all()]
    if not ids:
        await session.commit()
        return []

    await session.commit()
    rows = await session.scalars(select(GroupActivity).where(GroupActivity.id.in_(ids)))
    return list(rows)


def _counts_for(
    rows: Sequence[GroupActivity], kinds: frozenset[ActivityKind], recipient_id: int
) -> dict[ActivityKind, int]:
    """Total each kind the recipient asked for and did not do themselves.

    Excluded per row rather than per digest: when two people have been working
    in a group, each should hear what the other did, and neither should be told
    about their own afternoon.
    """
    counts: dict[ActivityKind, int] = {}
    for row in rows:
        if row.actor_id == recipient_id:
            continue
        kind = ActivityKind(row.kind)
        if kind in kinds:
            counts[kind] = counts.get(kind, 0) + row.count
    return counts


async def _deliver(
    session: AsyncSession,
    library: Library,
    rows: Sequence[GroupActivity],
    notify: Notify,
) -> int:
    """Tell everybody who asked, and return how many were told."""
    # Resolved per kind and merged, so one member subscribed to two kinds is
    # written to once.
    candidates: dict[int, User] = {}
    for kind in ActivityKind:
        for user in await groupprefs.subscribers(session, library, kind):
            candidates[user.id] = user

    told = 0
    for user in sorted(candidates.values(), key=lambda candidate: candidate.id):
        kinds = await groupprefs.subscribed_kinds(session, library, user_id=user.id)
        counts = _counts_for(rows, kinds, user.id)
        if not counts:
            # Either nothing of a kind they wanted, or all of it was their own
            # work. Telling somebody what they just did is the fastest way to
            # teach them to ignore the notification.
            continue

        subject = f"New activity in “{library.name}”"
        body = "\n".join(_describe(counts))
        await notifications.raise_for(
            session, user, kind="group_activity", subject=subject, body=body
        )
        told += 1

        if user.email:
            message = Message(
                to=user.email,
                subject=subject,
                body=(
                    f"Since you were last told, in the group library “{library.name}”:\n\n"
                    f"{body}\n\n"
                    "You are receiving this because you asked to be notified about "
                    "this group. Change that in the group's settings."
                ),
            )
            try:
                await notify(message)
            except Exception:
                # A digest is about something that already happened. Failing
                # here would mean sending it again on the next sweep, to
                # everybody, which is worse than not sending it at all.
                logger.exception("Could not send the group digest to %s", user.email)

    return told


async def sweep(
    session: AsyncSession,
    notify: Notify,
    *,
    quiet_period: timedelta = DEFAULT_QUIET_PERIOD,
) -> int:
    """Deliver every digest that is due, and return how many were sent.

    Safe to call at any time and from anywhere: a library with nothing settled
    is skipped, and the claim means two sweeps running at once cannot both send
    the same digest.
    """
    total = 0
    for library_id in await _settled_libraries(session, quiet_period):
        rows = await _claim(session, library_id)
        if not rows:
            continue

        library = await session.get(Library, library_id)
        if library is None:  # pragma: no cover - deleted between the two steps
            continue

        total += await _deliver(session, library, rows, notify)

    return total
