"""A federated sign-in between leaving here and coming back.

In the database rather than in memory, and that is the whole reason this module
exists rather than a dictionary somewhere. ``services/streaming.py`` and
``services/migrations.py`` both hold state in the process and are documented as
working behind one worker and no further; ``CLAUDE.md`` names that as a known
limitation. Signing in is not something that may break when a deployment adds a
second worker, and a browser that came back to a different one than it left
would otherwise be told its state was never issued.

Rows are single use -- :func:`consume` deletes as it reads -- so an
authorization code replayed with the same state finds nothing the second time.
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import AuthRequest, IdentityProvider
from altero.services import oidc


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def create(
    session: AsyncSession,
    provider: IdentityProvider,
    *,
    next_path: str = "/library",
    purpose: str = "login",
    user_id: int | None = None,
) -> AuthRequest:
    """Start a sign-in and return the row the callback will have to match."""
    # Expired rows go as new ones are made, which keeps the table bounded
    # without a scheduled job -- the same approach as sessions and login codes.
    await session.execute(delete(AuthRequest).where(AuthRequest.expires < _now()))

    pending = AuthRequest(
        state=secrets.token_urlsafe(32),
        provider_id=provider.id,
        code_verifier=oidc.generate_verifier(),
        nonce=oidc.generate_nonce(),
        next_path=next_path[:500],
        purpose=purpose,
        user_id=user_id,
        expires=_now() + oidc.REQUEST_LIFETIME,
    )
    session.add(pending)
    await session.commit()
    return pending


async def consume(session: AsyncSession, state: str) -> AuthRequest | None:
    """Return the request ``state`` names and spend it, or ``None``.

    Deleted as it is read, so the same state cannot answer twice. ``None``
    covers "never issued", "already used" and "too old" alike, because from the
    callback's side they are one fact: this is not a sign-in this server
    started.
    """
    if not state:
        return None

    pending = await session.scalar(select(AuthRequest).where(AuthRequest.state == state))
    if pending is None:
        return None

    # Read out before the row goes, since the caller needs it afterwards.
    detached = AuthRequest(
        state=pending.state,
        provider_id=pending.provider_id,
        code_verifier=pending.code_verifier,
        nonce=pending.nonce,
        next_path=pending.next_path,
        purpose=pending.purpose,
        user_id=pending.user_id,
        expires=pending.expires,
    )
    expired = pending.expires < _now()

    await session.delete(pending)
    await session.commit()

    return None if expired else detached
