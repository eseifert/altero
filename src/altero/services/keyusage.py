"""When and where an API key was last used.

The list of keys is only actionable if it can answer "which of these can I
revoke?". A key never used, or last seen months ago from an address nobody
recognises, is one to remove; without a record, every key looks alike and the
safe course is to leave them all.

Deliberately not an audit log. A syncing client makes a great many requests,
and writing on each would put a write in front of every read for a piece of
information nobody needs to the second. So a key is touched at most once per
:data:`INTERVAL_SECONDS` -- except when the address changes, which is the one
case somebody would want to see immediately.

The throttle is per process and in memory. Several workers may therefore each
write once per interval, which is a handful of rows a minute and buys not
having to coordinate. Nothing here is relied upon for correctness: the worst a
lost update costs is a slightly stale timestamp.
"""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ApiKey

logger = logging.getLogger("altero.keyusage")

#: How long to leave a key alone before recording its use again.
INTERVAL_SECONDS = 60

#: Longest user agent stored. Whatever arrived is cut to fit rather than
#: refused: it is a header, so it is whatever the caller chose to send.
MAX_USER_AGENT = 255

#: Longest address stored. An IPv6 address with an embedded IPv4 one is 45.
MAX_ADDRESS = 45

#: key id -> (monotonic time of last write, address written).
_seen: dict[int, tuple[float, str | None]] = {}


def reset() -> None:
    """Forget the throttle. For tests, and for nothing else."""
    _seen.clear()


def _should_write(key_id: int, address: str | None, now: float) -> bool:
    previous = _seen.get(key_id)
    if previous is None:
        return True
    written_at, written_address = previous
    if address != written_address:
        # A key showing up from somewhere new is the whole reason to look at
        # this column, so it is never delayed.
        return True
    return now - written_at >= INTERVAL_SECONDS


async def record(
    session: AsyncSession,
    key_id: int,
    *,
    address: str | None,
    user_agent: str | None,
    now: float | None = None,
) -> None:
    """Note that ``key_id`` was just used, if it is time to.

    Never raises. This is a convenience recorded alongside a request that has
    already been authorised; failing that request because a bookkeeping write
    did not land would trade something useful for something incidental.
    """
    moment = time.monotonic() if now is None else now
    trimmed_address = address[:MAX_ADDRESS] if address else None

    if not _should_write(key_id, trimmed_address, moment):
        return

    try:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(
                last_used=datetime.now(UTC).replace(tzinfo=None),
                last_address=trimmed_address,
                last_user_agent=user_agent[:MAX_USER_AGENT] if user_agent else None,
            )
        )
        await session.commit()
    except SQLAlchemyError:
        # A key revoked between authenticating and this write is a race, not a
        # fault, and any other database trouble will be reported by the real
        # work of the request.
        logger.debug("Could not record use of key %s", key_id, exc_info=True)
        await session.rollback()
        return

    _seen[key_id] = (moment, trimmed_address)
