"""Things to show a person the next time they look.

Email is not enough on its own. A self-hosted instance may have no relay
configured at all, an address may be unconfirmed, and mail is filtered and
lost; an invitation that exists only in an inbox is an invitation that
frequently never arrives. So anything worth telling somebody is also recorded
here, where the interface can show it.

Notifications hold rendered text rather than a payload to interpret later. What
a notice says should be what was true when it was raised -- a group renamed
afterwards must not silently rewrite history, and one deleted afterwards must
not turn its notice into a blank row.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import Notification, User

#: Newest first, and capped: this backs a panel, not an archive.
DEFAULT_LIMIT = 50


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def raise_for(
    session: AsyncSession,
    user: User,
    *,
    kind: str,
    subject: str,
    body: str = "",
    invitation_id: int | None = None,
) -> Notification:
    """Record something for ``user`` to see."""
    notification = Notification(
        user_id=user.id,
        kind=kind,
        subject=subject,
        body=body,
        invitation_id=invitation_id,
    )
    session.add(notification)
    await session.commit()
    return notification


async def list_for(
    session: AsyncSession, user: User, *, limit: int = DEFAULT_LIMIT
) -> list[Notification]:
    """Return this user's notifications, newest first."""
    result = await session.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created.desc(), Notification.id.desc())
        .limit(limit)
    )
    return list(result)


async def unread_count(session: AsyncSession, user: User) -> int:
    """Return how many are unread, which is what the badge shows."""
    return (
        await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read.is_(None))
        )
    ) or 0


def _require_own(notification: Notification, user: User) -> None:
    if notification.user_id != user.id:
        # Not found would be kinder to an attacker guessing ids; this is a
        # refusal either way and the id is not secret.
        raise ForbiddenError("That notification is not yours")


async def mark_read(session: AsyncSession, notification: Notification, user: User) -> None:
    """Mark one as read. Idempotent: the timestamp is not moved."""
    _require_own(notification, user)
    if notification.read is None:
        notification.read = _now()
        await session.commit()


async def mark_all_read(session: AsyncSession, user: User) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(None))
        .values(read=_now())
    )
    await session.commit()


async def mark_read_for_invitation(session: AsyncSession, user: User, invitation_id: int) -> None:
    """Mark whatever was raised about an invitation as read.

    Called when it is answered: acting on a notice *is* reading it, and leaving
    it bold afterwards trains people to ignore the badge.
    """
    await session.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.invitation_id == invitation_id,
            Notification.read.is_(None),
        )
        .values(read=_now())
    )
    await session.commit()
