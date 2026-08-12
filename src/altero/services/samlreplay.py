"""Remembering which SAML assertions have already been used.

Nothing in the SAML specification stops an assertion being presented twice --
the service provider is required to notice, and this is how altero does.

The insert *is* the check. A unique primary key on the assertion id means a
second attempt fails at the database rather than at a read-then-write that two
requests could interleave through, which matters because replaying the same
assertion twice in parallel is exactly what somebody attacking this would try.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import ConsumedAssertion, IdentityProvider

logger = logging.getLogger("altero.saml")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def consume(
    session: AsyncSession,
    provider: IdentityProvider,
    *,
    assertion_id: str,
    expires: datetime,
) -> None:
    """Record this assertion as used, or refuse because it already was.

    Rows past their own expiry go as new ones arrive, which keeps the table
    bounded without a scheduled job -- the same approach as sessions, login
    codes and auth requests.
    """
    await session.execute(delete(ConsumedAssertion).where(ConsumedAssertion.expires < _now()))
    await session.commit()

    # Read before the insert is attempted: a rollback expires the instance, and
    # touching an attribute afterwards is a lazy load in the wrong place.
    named = provider.slug
    provider_id = provider.id

    session.add(
        ConsumedAssertion(assertion_id=assertion_id, provider_id=provider_id, expires=expires)
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.warning("Assertion %s from %s was presented twice", assertion_id, named)
        raise ForbiddenError("That sign-in has already been used") from None
