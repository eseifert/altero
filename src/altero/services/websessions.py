"""The lifecycle of a browser session.

The token exists in one place only: the cookie in the browser. What is stored
here is its SHA-256, so a copy of the database -- a backup, a replica, a dump
in a bug report -- carries no working sessions. That is also why lookup hashes
the presented token rather than comparing anything reversible.

A plain SHA-256 is right here and would be wrong for a password: the token is
256 bits of output from ``secrets``, so there is no guessable input to grind
against, and the fast digest is exactly what a per-request lookup wants.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import User, WebSession

#: How long a session lives before it must be created again.
LIFETIME_DAYS = 30

#: Bytes of entropy in a session token.
TOKEN_BYTES = 32


def _now() -> datetime:
    """Return the current time as the naive UTC the columns store."""
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(token: str) -> str:
    """Return the digest stored for ``token``."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create(
    session: AsyncSession,
    user: User,
    *,
    pending_factor: str | None = None,
    user_agent: str = "",
) -> tuple[str, WebSession]:
    """Open a session for ``user`` and return its token and record.

    The token is returned here and nowhere else; it cannot be recovered from
    the record afterwards.
    """
    # Expired rows are cleared as sessions are opened, which keeps the table
    # bounded without a scheduled job -- the same approach as login sessions.
    await session.execute(delete(WebSession).where(WebSession.expires < _now()))

    token = secrets.token_urlsafe(TOKEN_BYTES)
    record = WebSession(
        token_hash=hash_token(token),
        user_id=user.id,
        pending_factor=pending_factor,
        expires=_now() + timedelta(days=LIFETIME_DAYS),
        user_agent=user_agent[:255],
    )
    session.add(record)
    await session.commit()
    return token, record


async def lookup(session: AsyncSession, token: str | None) -> WebSession | None:
    """Return the live session ``token`` identifies, if any.

    Expiry is applied here rather than left to the caller, so that there is no
    path on which an out-of-date session is honoured by someone who forgot to
    check. A session belonging to a suspended account is refused for the same
    reason: :func:`altero.services.admin.set_disabled` ends those sessions, and
    this is what makes suspension a property of the credential rather than of
    a cleanup step that could be raced by a sign-in.

    The owner is fetched in the same statement, so this stays one query on the
    path every request under ``/web`` takes.
    """
    if not token:
        return None

    row = (
        await session.execute(
            select(WebSession, User.disabled_at)
            .join(User, User.id == WebSession.user_id)
            .where(WebSession.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        return None

    record, disabled_at = row
    if disabled_at is not None or record.expires < _now():
        return None
    return record


def is_authenticated(record: WebSession) -> bool:
    """Return whether ``record`` has cleared every factor it needs.

    A session holding an outstanding factor is a real row with a real cookie,
    and is deliberately not the same thing as being logged in.
    """
    return record.pending_factor is None


async def touch(session: AsyncSession, record: WebSession) -> None:
    """Record that the session was used."""
    record.last_seen = _now()
    await session.commit()


async def revoke(session: AsyncSession, record: WebSession) -> None:
    """End one session."""
    await session.delete(record)
    await session.commit()


async def revoke_all(
    session: AsyncSession,
    user: User,
    *,
    keep: WebSession | None = None,
) -> None:
    """End every session belonging to ``user``, optionally sparing one.

    ``keep`` is how a password change avoids logging out the browser that
    performed it while still turning off everywhere else.
    """
    statement = delete(WebSession).where(WebSession.user_id == user.id)
    if keep is not None:
        statement = statement.where(WebSession.id != keep.id)
    await session.execute(statement)
    await session.commit()
